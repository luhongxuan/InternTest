"""執行迴圈：使用者 approve 後才會進到這裡。

每一輪：截圖 -> 模型決定動作 -> schema 驗證 -> 安全檢查 -> 執行 -> 記錄。
迴圈在 finish/fail/max_steps/重複/無變化/使用者中止 時停止。
"""

import json
from typing import Callable, Dict, List, Optional

from . import prompts, safety, schemas
from .state import TaskState, can_transition


class ExecutionResult:
    def __init__(self, state: TaskState, reason: str, steps: int):
        self.state = state
        self.reason = reason
        self.steps = steps


class AgentLoop:
    def __init__(self, client, screen_manager, tool_executor, model, logger, cfg,
                 confirm_fn: Callable[[str], bool]):
        self.client = client
        self.screen = screen_manager
        self.tools = tool_executor
        self.model = model
        self.logger = logger
        self.cfg = cfg
        self.confirm_fn = confirm_fn  # (message) -> bool，交給 CLI 問使用者
        self.state = TaskState.IDLE
        self.history: List[Dict] = []

    def _set_state(self, dst: TaskState):
        if self.state != dst and not can_transition(self.state, dst):
            # 只記錄，不強制中斷（避免邊界情況卡死），但方便除錯
            self.logger.log("illegal_transition", src=self.state.value, dst=dst.value)
        self.state = dst

    def _history_text(self) -> str:
        recent = self.history[-self.cfg.HISTORY_WINDOW:]
        lines = []
        for h in recent:
            lines.append(f"- {h['action'].get('action')} "
                         f"reason={h['action'].get('reason','')[:40]} "
                         f"result={'ok' if h['result'].get('ok') else 'fail'}")
        return "\n".join(lines)

    def run(self, task: str, plan: Dict) -> ExecutionResult:
        self._set_state(TaskState.EXECUTING)
        guard = safety.LoopGuard(self.cfg.MAX_SAME_ACTION_REPEAT, self.cfg.MAX_NO_CHANGE)
        plan_text = json.dumps(plan["plan"], ensure_ascii=False)
        consecutive_parse_fail = 0

        for step in range(1, self.cfg.MAX_STEPS + 1):
            from .logger import step_banner
            step_banner(step, self.state.value)

            shot = self.screen.capture(tag=f"step{step:02d}")

            # 畫面無變化偵測
            nc = guard.record_screen(shot["phash"])
            if nc:
                self._set_state(TaskState.FAILED)
                self.logger.log("stop", step=step, reason=nc)
                return ExecutionResult(self.state, nc, step)

            # 呼叫模型
            mw, mh = shot["model_size"]
            user = prompts.build_execution_user(task, plan_text, self._history_text(), mw, mh)
            parsed, raw = self.client.chat_json(
                self.model, prompts.EXECUTION_SYSTEM, user, image_b64=shot["image_b64"])

            self.logger.log("model_response", step=step, screenshot=shot["path"],
                            state=self.state.value, screen_real=shot["real_size"],
                            screen_model=shot["model_size"], raw=raw[:2000],
                            parsed_ok=parsed is not None)

            if parsed is None:
                consecutive_parse_fail += 1
                print(f"[!] JSON 解析失敗（連續 {consecutive_parse_fail} 次）")
                if consecutive_parse_fail >= 2:
                    self._set_state(TaskState.FAILED)
                    self.logger.log("stop", step=step, reason="JSON 連續解析失敗")
                    return ExecutionResult(self.state, "JSON 連續解析失敗", step)
                continue
            consecutive_parse_fail = 0

            # schema 驗證
            ok, err, action = schemas.validate_action(parsed)
            self.logger.log("action_validation", step=step, ok=ok, error=err, action=action)
            if not ok:
                print(f"[!] 非法 action：{err}")
                # 給模型一次改正機會，記在歷史裡
                self.history.append({"action": {"action": "invalid", "reason": err},
                                     "result": {"ok": False, "error": err}})
                continue

            print(f"[action] {action['action']}  reason={action.get('reason','')}")

            # 終止型動作
            if action["action"] == "finish_task":
                self._set_state(TaskState.COMPLETED)
                self.logger.log("finish", step=step, reason=action.get("reason", ""))
                return ExecutionResult(self.state, action.get("reason", "任務完成"), step)
            if action["action"] == "fail_task":
                self._set_state(TaskState.FAILED)
                self.logger.log("fail", step=step, reason=action.get("reason", ""))
                return ExecutionResult(self.state, action.get("reason", "模型放棄"), step)

            # 安全檢查
            verdict, sreason = safety.check_action_safety(action)
            self.logger.log("action_safety", step=step, verdict=verdict, reason=sreason)
            if verdict == "block":
                print(f"[SAFETY] 已封鎖：{sreason}")
                self.history.append({"action": action, "result": {"ok": False, "error": sreason}})
                continue
            if verdict == "confirm":
                self._set_state(TaskState.PAUSED)
                approved = self.confirm_fn(sreason or "此動作需要確認")
                self.logger.log("user_confirm", step=step, approved=approved, reason=sreason)
                if not approved:
                    self._set_state(TaskState.CANCELLED)
                    return ExecutionResult(self.state, "使用者拒絕高風險動作", step)
                self._set_state(TaskState.EXECUTING)
                if action["action"] == "request_user_confirmation":
                    # 只是確認，本身不執行 OS 動作，繼續下一輪
                    self.history.append({"action": action, "result": {"ok": True, "confirmed": True}})
                    continue

            # 重複動作偵測（在執行前）
            rep = guard.record_action(action)
            if rep:
                self._set_state(TaskState.FAILED)
                self.logger.log("stop", step=step, reason=rep)
                return ExecutionResult(self.state, rep, step)

            # screenshot 動作：不需 OS 操作，直接進下一輪重新觀察
            if action["action"] == "screenshot":
                self.history.append({"action": action, "result": {"ok": True, "noop": "screenshot"}})
                continue

            # 實際執行
            result = self.tools.execute(action, shot["scale"])
            self.logger.log("action_result", step=step, action=action, result=result)
            print(f"[result] {'ok' if result.get('ok') else 'FAIL: ' + str(result.get('error'))}")
            self.history.append({"action": action, "result": result})

        self._set_state(TaskState.FAILED)
        self.logger.log("stop", reason=f"達到 max_steps={self.cfg.MAX_STEPS}")
        return ExecutionResult(self.state, f"達到最大步數 {self.cfg.MAX_STEPS}", self.cfg.MAX_STEPS)
