"""Session 執行核心（headless，供後端 API 使用）。

和 CLI 版 agent_loop 相同的迴圈邏輯，但差別在：
- 不用 print / input()，改成把每步事件 append 到 events，讓前端輪詢。
- 遇到需要確認的動作時，設定 pending_confirm 並「阻塞等待」前端回覆
  （threading.Event），而不是 CLI 的 input()。
- 支援外部 cancel（前端按取消）。

依賴（screen / tools / client / planner）以參數注入，方便在無 GUI 環境測試。
"""

import json
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from agent import prompts, safety, schemas
from agent.state import TaskState, can_transition


class Session:
    def __init__(self, task: str, max_steps: int):
        self.id = uuid.uuid4().hex[:12]
        self.task = task
        self.max_steps = max_steps
        self.state = TaskState.IDLE
        self.plan: Optional[Dict] = None
        self.steps_done = 0
        self.reason = ""
        self.events: List[Dict] = []
        self.latest_screenshot: Optional[str] = None
        self.latest_action: Optional[Dict] = None

        # 確認機制
        self.pending_confirm: Optional[Dict] = None   # {"message": ...}
        self._confirm_event = threading.Event()
        self._confirm_result = False

        # 取消
        self._cancel = threading.Event()

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # --- 事件 ---
    def emit(self, kind: str, **fields: Any) -> None:
        with self._lock:
            self.events.append({
                "seq": len(self.events),
                "time": time.strftime("%H:%M:%S"),
                "kind": kind,
                **fields,
            })

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "id": self.id,
                "task": self.task,
                "state": self.state.value,
                "steps_done": self.steps_done,
                "max_steps": self.max_steps,
                "reason": self.reason,
                "plan": self.plan,
                "latest_action": self.latest_action,
                "latest_screenshot": self.latest_screenshot,
                "pending_confirm": self.pending_confirm,
                "event_count": len(self.events),
            }

    def events_since(self, seq: int) -> List[Dict]:
        with self._lock:
            return [e for e in self.events if e["seq"] >= seq]

    # --- 控制 ---
    def request_cancel(self) -> None:
        self._cancel.set()
        self._confirm_event.set()  # 若正卡在等待確認，解除阻塞

    def answer_confirm(self, approved: bool) -> None:
        self._confirm_result = approved
        self.pending_confirm = None
        self._confirm_event.set()

    def _wait_confirm(self, message: str) -> bool:
        self.pending_confirm = {"message": message}
        self._confirm_event.clear()
        self.emit("await_confirm", message=message)
        # 等前端回覆，同時定期檢查取消
        while not self._confirm_event.wait(timeout=0.5):
            if self._cancel.is_set():
                return False
        if self._cancel.is_set():
            return False
        return self._confirm_result


class SessionRunner:
    """把單一 Session 跑完。deps 以參數注入。"""

    def __init__(self, session: Session, client, screen, tools, logger, cfg,
                 executor_model: str):
        self.s = session
        self.client = client
        self.screen = screen
        self.tools = tools
        self.logger = logger
        self.cfg = cfg
        self.model = executor_model

    def _set_state(self, dst: TaskState) -> None:
        if self.s.state != dst and not can_transition(self.s.state, dst):
            self.logger.log("illegal_transition", src=self.s.state.value, dst=dst.value)
        self.s.state = dst
        self.s.emit("state", state=dst.value)

    def _history_text(self) -> str:
        recent = self.s.events[-self.cfg.HISTORY_WINDOW * 3:]
        acts = [e for e in recent if e["kind"] == "action"][-self.cfg.HISTORY_WINDOW:]
        lines = [f"- {a.get('action')} reason={str(a.get('reason',''))[:40]} "
                 f"result={a.get('result_ok')}" for a in acts]
        return "\n".join(lines)

    def run(self) -> None:
        s = self.s
        if s._cancel.is_set():
            self._finish(TaskState.CANCELLED, "已取消")
            return
        if not s.plan:
            self._finish(TaskState.FAILED, "沒有已批准的計畫")
            return

        self._set_state(TaskState.EXECUTING)
        guard = safety.LoopGuard(self.cfg.MAX_SAME_ACTION_REPEAT, self.cfg.MAX_NO_CHANGE)
        plan_text = json.dumps(s.plan["plan"], ensure_ascii=False)
        parse_fail = 0

        for step in range(1, s.max_steps + 1):
            if s._cancel.is_set():
                self._finish(TaskState.CANCELLED, "使用者取消")
                return
            s.steps_done = step

            shot = self.screen.capture(tag=f"step{step:02d}")
            s.latest_screenshot = shot["path"]

            nc = guard.record_screen(shot["phash"])
            if nc:
                self._finish(TaskState.FAILED, nc)
                return

            mw, mh = shot["model_size"]
            user = prompts.build_execution_user(s.task, plan_text, self._history_text(), mw, mh)
            parsed, raw = self.client.chat_json(
                self.model, prompts.EXECUTION_SYSTEM, user, image_b64=shot["image_b64"])
            self.logger.log("model_response", step=step, screenshot=shot["path"],
                            raw=raw[:2000], parsed_ok=parsed is not None)

            if parsed is None:
                parse_fail += 1
                s.emit("parse_fail", step=step, count=parse_fail)
                if parse_fail >= 2:
                    self._finish(TaskState.FAILED, "JSON 連續解析失敗")
                    return
                continue
            parse_fail = 0

            ok, err, action = schemas.validate_action(parsed)
            self.logger.log("action_validation", step=step, ok=ok, error=err, action=action)
            if not ok:
                s.emit("invalid_action", step=step, error=err)
                continue

            s.latest_action = action
            s.emit("action", step=step, action=action.get("action"),
                   reason=action.get("reason", ""), detail=action, result_ok=None)

            if action["action"] == "finish_task":
                self._finish(TaskState.COMPLETED, action.get("reason", "任務完成"))
                return
            if action["action"] == "fail_task":
                self._finish(TaskState.FAILED, action.get("reason", "模型放棄"))
                return

            verdict, sreason = safety.check_action_safety(action)
            self.logger.log("action_safety", step=step, verdict=verdict, reason=sreason)
            if verdict == "block":
                s.emit("blocked", step=step, reason=sreason)
                continue
            if verdict == "confirm":
                self._set_state(TaskState.PAUSED)
                approved = s._wait_confirm(sreason or "此動作需要確認")
                self.logger.log("user_confirm", step=step, approved=approved)
                if not approved:
                    self._finish(TaskState.CANCELLED, "使用者拒絕高風險動作")
                    return
                self._set_state(TaskState.EXECUTING)
                if action["action"] == "request_user_confirmation":
                    continue

            rep = guard.record_action(action)
            if rep:
                self._finish(TaskState.FAILED, rep)
                return

            if action["action"] == "screenshot":
                s.emit("observe", step=step)
                continue

            result = self.tools.execute(action, shot["scale"])
            self.logger.log("action_result", step=step, action=action, result=result)
            s.emit("result", step=step, ok=result.get("ok"),
                   error=result.get("error"), detail=result)
            # 回填最近動作的結果，供 history 使用
            s.emit("action", step=step, action=action.get("action"),
                   reason="", detail=None, result_ok=result.get("ok"))

        self._finish(TaskState.FAILED, f"達到最大步數 {s.max_steps}")

    def _finish(self, state: TaskState, reason: str) -> None:
        self._set_state(state)
        self.s.reason = reason
        self.s.pending_confirm = None
        self.s.emit("done", state=state.value, reason=reason, steps=self.s.steps_done)
        self.logger.log("run_end", state=state.value, reason=reason, steps=self.s.steps_done)
