"""Agent 執行迴圈 — Browser 版

在原有架構上加入 BrowserObservationProvider + BrowserActionExecutor。
原有的 ScreenManager + ToolExecutor 保留作為 fallback（observation_mode="screenshot"）。

observation_mode:
  "browser"    — 透過 WebSocket bridge 取得元素 + 截圖，再呼叫模型
  "screenshot" — 原有純截圖模式（fallback）
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import config
from agent import prompts, schemas
from browser.observation_provider import (
    BrowserObservationProvider,
    format_elements_for_prompt,
)
from browser.action_executor import BrowserActionExecutor

logger = logging.getLogger(__name__)

OBSERVATION_MODE_BROWSER = "browser"
OBSERVATION_MODE_SCREENSHOT = "screenshot"


@dataclass
class StepLog:
    """單步執行記錄，對應需求文件的 logging 欄位。"""
    session_id: str
    task: str
    current_step: int
    observation_mode: str
    current_url: str
    page_title: str
    screenshot_path: str
    interactive_elements_count: int
    model_raw_response: str
    parsed_action: Optional[Dict]
    schema_validation_ok: bool
    schema_validation_error: str
    execution_result: Optional[Dict]
    error_message: str
    timestamp: float


class AgentLoop:
    """瀏覽器操作執行迴圈。

    Args:
        client              : OllamaClient
        observation_provider: BrowserObservationProvider（browser 模式）
        action_executor     : BrowserActionExecutor（browser 模式）
        screen_manager      : ScreenManager（screenshot fallback）
        tool_executor       : ToolExecutor（screenshot fallback）
        vision_model        : 視覺模型名稱
        observation_mode    : "browser" | "screenshot"
        max_steps           : 最多執行步數
        session_id          : 用於 log
    """

    def __init__(
        self,
        client,
        observation_provider: Optional[BrowserObservationProvider],
        action_executor: Optional[BrowserActionExecutor],
        screen_manager=None,
        tool_executor=None,
        vision_model: str = config.VISION_MODEL,
        observation_mode: str = OBSERVATION_MODE_BROWSER,
        max_steps: int = config.MAX_STEPS,
        session_id: str = "default",
    ):
        self.client = client
        self.observation_provider = observation_provider
        self.action_executor = action_executor
        self.screen = screen_manager          # fallback
        self.tools = tool_executor            # fallback
        self.vision_model = vision_model
        self.observation_mode = observation_mode
        self.max_steps = max_steps
        self.session_id = session_id
        self.history: List[Dict] = []
        self.step_logs: List[StepLog] = []

    def _history_text(self) -> str:
        recent = self.history[-config.HISTORY_WINDOW:]
        lines = []
        for h in recent:
            a = h["action"]
            lines.append(
                f"- {a.get('action')} "
                f"element={a.get('element_id', a.get('x',''))} "
                f"reason={str(a.get('reason',''))[:40]} "
                f"result={'ok' if h['result'].get('ok') else 'fail'}"
            )
        return "\n".join(lines)

    async def run(self, task: str, approved_plan: List[Dict]) -> Dict[str, Any]:
        """執行迴圈主體。回傳 {state, reason, steps, logs}。"""
        parse_fail_count = 0
        total_steps = len(approved_plan)

        for step in range(1, self.max_steps + 1):
            logger.info("[Loop] step=%d session=%s", step, self.session_id)

            step_log = StepLog(
                session_id=self.session_id,
                task=task,
                current_step=step,
                observation_mode=self.observation_mode,
                current_url="", page_title="", screenshot_path="",
                interactive_elements_count=0,
                model_raw_response="", parsed_action=None,
                schema_validation_ok=False, schema_validation_error="",
                execution_result=None, error_message="",
                timestamp=time.time(),
            )

            # ----------------------------------------------------------------
            # 1. 觀察
            # ----------------------------------------------------------------
            if self.observation_mode == OBSERVATION_MODE_BROWSER:
                obs = await self.observation_provider.get_observation()

                if obs.error:
                    logger.warning("[Loop] 觀察失敗: %s", obs.error)
                    step_log.error_message = obs.error
                    self.step_logs.append(step_log)
                    return {"state": "failed", "reason": f"取得頁面觀察失敗: {obs.error}", "steps": step}

                step_log.current_url = obs.page_url
                step_log.page_title = obs.page_title
                step_log.screenshot_path = obs.screenshot_path
                step_log.interactive_elements_count = len(obs.elements)

                elements_text = format_elements_for_prompt(obs.elements)
                user_prompt = prompts.build_browser_execution_user(
                    task=task,
                    plan=approved_plan,
                    current_step=step,
                    history_text=self._history_text(),
                    page_url=obs.page_url,
                    page_title=obs.page_title,
                    elements_text=elements_text,
                    screenshot_width=obs.screenshot_width,
                    screenshot_height=obs.screenshot_height,
                )
                system_prompt = prompts.BROWSER_EXECUTION_SYSTEM
                image_b64 = obs.screenshot_base64 or None

            else:
                # fallback: 純截圖模式
                shot = self.screen.capture_screen()
                step_log.screenshot_path = shot["path"]
                mw, mh = shot["model_size"]
                plan_text = json.dumps(approved_plan, ensure_ascii=False)
                user_prompt = prompts.build_execution_user(
                    task, plan_text, self._history_text(), mw, mh
                )
                system_prompt = prompts.EXECUTION_SYSTEM
                image_b64 = shot["image_base64"]

            # ----------------------------------------------------------------
            # 2. 模型推論（單獨計時）
            # ----------------------------------------------------------------
            t_infer = time.time()
            parsed, raw = self.client.chat_json(
                self.vision_model, system_prompt, user_prompt, image_b64=image_b64
            )
            infer_sec = time.time() - t_infer

            step_log.model_raw_response = raw[:2000]
            logger.info("[Loop] step=%d infer=%.2fs parsed=%s", step, infer_sec, parsed is not None)

            if parsed is None:
                parse_fail_count += 1
                step_log.error_message = f"JSON 解析失敗（連續 {parse_fail_count} 次）"
                self.step_logs.append(step_log)
                if parse_fail_count >= 2:
                    return {"state": "failed", "reason": "模型輸出連續無法解析", "steps": step}
                continue
            parse_fail_count = 0

            # ----------------------------------------------------------------
            # 3. Schema 驗證
            # ----------------------------------------------------------------
            ok, err, action = schemas.validate_action(parsed)
            step_log.schema_validation_ok = ok
            step_log.schema_validation_error = err
            step_log.parsed_action = action

            if not ok:
                logger.warning("[Loop] schema 驗證失敗: %s", err)
                step_log.error_message = f"schema 驗證失敗: {err}"
                self.step_logs.append(step_log)
                self.history.append({"action": {"action": "invalid"}, "result": {"ok": False, "error": err}})
                continue

            action_name = action["action"]
            logger.info("[Loop] action=%s reason=%s", action_name, action.get("reason", "")[:60])

            # ----------------------------------------------------------------
            # 4. 終止型 action
            # ----------------------------------------------------------------
            if action_name == "finish_task":
                self.step_logs.append(step_log)
                return {"state": "completed", "reason": action.get("reason", "任務完成"), "steps": step}

            if action_name == "fail_task":
                self.step_logs.append(step_log)
                return {"state": "failed", "reason": action.get("reason", "模型放棄"), "steps": step}

            if action_name == "request_user_confirmation":
                self.step_logs.append(step_log)
                return {"state": "awaiting_confirmation", "reason": action.get("reason", ""), "steps": step}

            if action_name == "screenshot":
                # pure screenshot observe，直接進下一輪
                self.history.append({"action": action, "result": {"ok": True, "noop": "screenshot"}})
                self.step_logs.append(step_log)
                continue

            # ----------------------------------------------------------------
            # 5. 執行
            # ----------------------------------------------------------------
            if self.observation_mode == OBSERVATION_MODE_BROWSER and self.action_executor:
                result = await self.action_executor.execute(action)
            else:
                # fallback: ToolExecutor (pyautogui)
                result = self.tools.execute(action, shot.get("scale", 1.0))

            step_log.execution_result = result
            self.step_logs.append(step_log)
            self.history.append({"action": action, "result": result})

            if not result.get("ok"):
                logger.warning("[Loop] 執行失敗: %s", result.get("error"))

        return {"state": "failed", "reason": f"達到最大步數 {self.max_steps}", "steps": self.max_steps}
