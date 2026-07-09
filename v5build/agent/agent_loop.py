"""執行迴圈 — 支援 browser 模式與 screenshot fallback 模式。

V1 原有的完整機制全部保留：
  - TaskState 狀態機
  - safety.LoopGuard（重複動作 / 畫面無變化偵測）
  - safety.check_action_safety（hotkey 封鎖 / 確認機制）
  - RunLogger JSONL 記錄
  - confirm_fn 使用者確認回呼

新增（最小改動）：
  - observation_mode 參數："browser" | "screenshot"
  - browser 模式下改用 BrowserObservationProvider 觀察、BrowserActionExecutor 執行
  - browser 模式的 log 額外記錄 url / page_title / elements_count / ws 連線狀態
"""

import json
import logging
from typing import Callable, Dict, List, Optional

from . import prompts, safety, schemas
from .logger import RunLogger, step_banner
from .state import TaskState, can_transition

logger = logging.getLogger(__name__)

OBSERVATION_MODE_BROWSER = "browser"
OBSERVATION_MODE_SCREENSHOT = "screenshot"


class ExecutionResult:
    def __init__(self, state: TaskState, reason: str, steps: int):
        self.state = state
        self.reason = reason
        self.steps = steps


class AgentLoop:
    """瀏覽器 / 桌面雙模式執行迴圈。

    browser 模式：observation_provider + action_executor（WebSocket bridge）
    screenshot 模式：screen_manager + tool_executor（pyautogui）
    """

    def __init__(
        self,
        client,
        screen_manager,
        tool_executor,
        model: str,
        run_logger: RunLogger,
        cfg,
        confirm_fn: Callable[[str], bool],
        observation_provider=None,
        action_executor=None,
        observation_mode: str = OBSERVATION_MODE_SCREENSHOT,
    ):
        # 共用
        self.client = client
        self.model = model
        self.logger = run_logger
        self.cfg = cfg
        self.confirm_fn = confirm_fn
        self.observation_mode = observation_mode
        self.state = TaskState.IDLE
        self.history: List[Dict] = []

        # Screenshot 模式
        self.screen = screen_manager
        self.tools = tool_executor

        # Browser 模式
        self.observation_provider = observation_provider
        self.action_executor = action_executor

    def _set_state(self, dst: TaskState) -> None:
        if self.state != dst and not can_transition(self.state, dst):
            self.logger.log("illegal_transition", src=self.state.value, dst=dst.value)
        self.state = dst

    def _history_text(self) -> str:
        recent = self.history[-self.cfg.HISTORY_WINDOW:]
        lines = []
        for h in recent:
            a = h["action"]
            name = a.get("action", "")
            detail = a.get("element_id", "") or f"({a.get('x','')},{a.get('y','')})" if name in ("click_element","click","click_coordinate") else ""
            lines.append(
                f"- {name} {detail} reason={str(a.get('reason',''))[:40]} "
                f"result={'ok' if h['result'].get('ok') else 'fail'}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 主迴圈
    # ------------------------------------------------------------------

    async def run(self, task: str, plan: Dict) -> ExecutionResult:
        self._set_state(TaskState.EXECUTING)
        guard = safety.LoopGuard(self.cfg.MAX_SAME_ACTION_REPEAT, self.cfg.MAX_NO_CHANGE)
        plan_steps = plan.get("plan", [])
        plan_text = json.dumps(plan_steps, ensure_ascii=False)
        consecutive_parse_fail = 0

        for step in range(1, self.cfg.MAX_STEPS + 1):
            step_banner(step, self.state.value)

            # ---- 觀察 ----
            if self.observation_mode == OBSERVATION_MODE_BROWSER:
                obs_result = await self._observe_browser(step)
                if obs_result is not None:          # 觀察失敗，直接回傳
                    return obs_result
                obs = self._last_obs           # _observe_browser 設定的暫存
                image_b64 = obs.screenshot_base64 or None
                system_prompt = prompts.BROWSER_EXECUTION_SYSTEM
                from browser.observation_provider import format_elements_for_prompt
                user_prompt = prompts.build_browser_execution_user(
                    task=task,
                    plan=plan_steps,
                    current_step=step,
                    history_text=self._history_text(),
                    page_url=obs.page_url,
                    page_title=obs.page_title,
                    elements_text=format_elements_for_prompt(obs.elements),
                    screenshot_width=obs.screenshot_width,
                    screenshot_height=obs.screenshot_height,
                )
                screen_hash = obs.screenshot_path   # browser 模式用截圖路徑當 hash key

                self.logger.log(
                    "browser_observation",
                    step=step,
                    url=obs.page_url,
                    page_title=obs.page_title,
                    elements_count=len(obs.elements),
                    screenshot_path=obs.screenshot_path,
                    ws_connected=self.action_executor.bridge.is_connected if self.action_executor else False,
                    observation=[vars(e) | {"bounds": vars(e.bounds)} for e in obs.elements],
                )
            else:
                shot = self.screen.capture(tag=f"step{step:02d}")
                nc = guard.record_screen(shot["phash"])
                if nc:
                    self._set_state(TaskState.FAILED)
                    self.logger.log("stop", step=step, reason=nc)
                    return ExecutionResult(self.state, nc, step)

                mw, mh = shot["model_size"]
                image_b64 = shot["image_b64"]
                system_prompt = prompts.EXECUTION_SYSTEM
                user_prompt = prompts.build_execution_user(
                    task, plan_text, self._history_text(), mw, mh
                )
                screen_hash = shot["phash"]

                self.logger.log(
                    "screenshot_observation",
                    step=step,
                    screenshot=shot["path"],
                    screen_real=shot["real_size"],
                    screen_model=shot["model_size"],
                )

            # ---- 模型推論 ----
            parsed, raw = self.client.chat_json(
                self.model, system_prompt, user_prompt, image_b64=image_b64
            )
            self.logger.log(
                "model_response",
                step=step,
                state=self.state.value,
                raw=raw[:2000],
                parsed_ok=parsed is not None,
            )
            
            if parsed is None:
                consecutive_parse_fail += 1
                print(f"[!] JSON 解析失敗（連續 {consecutive_parse_fail} 次）")
                if consecutive_parse_fail >= 2:
                    self._set_state(TaskState.FAILED)
                    self.logger.log("stop", step=step, reason="JSON 連續解析失敗")
                    return ExecutionResult(self.state, "JSON 連續解析失敗", step)
                continue
            consecutive_parse_fail = 0

            # ---- Schema 驗證 ----
            ok, err, action = schemas.validate_action(parsed)
            self.logger.log("action_validation", step=step, ok=ok, error=err, action=action)
            if not ok:
                print(f"[!] 非法 action：{err}")
                self.history.append({"action": {"action": "invalid", "reason": err},
                                     "result": {"ok": False, "error": err}})
                continue

            print(f"[action] {action['action']}  reason={action.get('reason', '')}")

            # ---- 終止型 ----
            if action["action"] == "finish_task":
                self._set_state(TaskState.COMPLETED)
                self.logger.log("finish", step=step, reason=action.get("reason", ""))
                return ExecutionResult(self.state, action.get("reason", "任務完成"), step)
            if action["action"] == "fail_task":
                self._set_state(TaskState.FAILED)
                self.logger.log("fail", step=step, reason=action.get("reason", ""))
                return ExecutionResult(self.state, action.get("reason", "模型放棄"), step)

            # ---- 安全檢查（保留 V1 完整機制）----
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
                    self.history.append({"action": action, "result": {"ok": True, "confirmed": True}})
                    continue

            # ---- 重複動作偵測 ----
            rep = guard.record_action(action)
            if rep:
                self._set_state(TaskState.FAILED)
                self.logger.log("stop", step=step, reason=rep)
                return ExecutionResult(self.state, rep, step)

            # ---- screenshot 動作（不需執行，重新觀察）----
            if action["action"] == "screenshot":
                self.history.append({"action": action, "result": {"ok": True, "noop": "screenshot"}})
                continue

            # ---- 執行 ----
            if self.observation_mode == OBSERVATION_MODE_BROWSER and self.action_executor:
                import asyncio
                result = await self.action_executor.execute(action)
            else:
                result = self.tools.execute(action, shot["scale"])

            self.logger.log("action_result", step=step, action=action, result=result)
            print(f"[result] {'ok' if result.get('ok') else 'FAIL: ' + str(result.get('error'))}")
            self.history.append({"action": action, "result": result})

        self._set_state(TaskState.FAILED)
        self.logger.log("stop", reason=f"達到 max_steps={self.cfg.MAX_STEPS}")
        return ExecutionResult(self.state, f"達到最大步數 {self.cfg.MAX_STEPS}", self.cfg.MAX_STEPS)

    async def _observe_browser(self, step: int) -> Optional[ExecutionResult]:
        """取得 browser observation；失敗回傳 ExecutionResult，成功回傳 None（結果存 self._last_obs）。"""
        import asyncio
        obs = await self.observation_provider.get_observation()

        if obs.error:
            self._set_state(TaskState.FAILED)
            self.logger.log("stop", step=step, reason=f"觀察失敗: {obs.error}")
            return ExecutionResult(self.state, f"取得頁面觀察失敗: {obs.error}", step)
        self._last_obs = obs
        return None
