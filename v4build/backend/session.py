"""Session — 管理單一任務的生命週期與狀態。

Session 狀態：
  idle → planning → awaiting_approval → executing → completed / failed / cancelled

SessionRunner 負責：
  1. 取得 BrowserObservation（透過 BrowserBridgeManager）
  2. 呼叫 AgentLoop.run()
  3. 把每步事件 append 到 events list（供前端輪詢）
  4. 記錄完整 step log
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import config
from agent.agent_loop import AgentLoop, OBSERVATION_MODE_BROWSER
from agent.model_client import OllamaClient
from agent.screen import ScreenManager
from agent.tools import ToolExecutor
from browser.action_executor import BrowserActionExecutor
from browser.observation_provider import BrowserBridgeManager, BrowserObservationProvider

logger = logging.getLogger(__name__)


# 假資料 plan（第一版測試用）—— 後續接真正的 Ollama Planner
MOCK_THSR_PLAN = {
    "task_summary": "查詢台灣高鐵從台北到台中，明天上午 09:00 左右出發的班次資訊。",
    "safety_check": {
        "is_safe": True,
        "risk_level": "low",
        "reason": "此任務只涉及查詢公開交通班次資訊，不包含付款、訂票、登入帳號、輸入個資或送出交易。"
    },
    "plan": [
        {"step": 1, "goal": "觀察目前瀏覽器畫面，確認是否已在高鐵查詢頁面或需要開啟高鐵網站。", "expected_action_type": "screenshot"},
        {"step": 2, "goal": "點擊出發站欄位，準備選擇或輸入台北作為出發站。", "expected_action_type": "click_element"},
        {"step": 3, "goal": "輸入或選擇出發站為台北。", "expected_action_type": "type_text"},
        {"step": 4, "goal": "點擊抵達站欄位，準備選擇或輸入台中作為抵達站。", "expected_action_type": "click_element"},
        {"step": 5, "goal": "輸入或選擇抵達站為台中。", "expected_action_type": "type_text"},
        {"step": 6, "goal": "點擊日期欄位，選擇明天的日期。", "expected_action_type": "click_element"},
        {"step": 7, "goal": "點擊時間欄位，選擇上午 09:00 左右的出發時間。", "expected_action_type": "click_element"},
        {"step": 8, "goal": "點擊查詢按鈕，送出班次查詢。", "expected_action_type": "click_element"},
        {"step": 9, "goal": "觀察查詢結果頁面，確認是否已顯示符合條件的高鐵班次。", "expected_action_type": "screenshot"},
        {"step": 10, "goal": "如果畫面已顯示班次資訊，整理目前查詢結果並結束任務。", "expected_action_type": "finish_task"},
    ],
    "requires_user_confirmation": True,
    "question_to_user": "是否同意依此計畫開始操作？"
}


class Session:
    """單一任務的狀態容器，事件列表供前端輪詢。"""

    def __init__(self, task: str = "", use_mock_plan: bool = False):
        self.session_id: str = uuid.uuid4().hex[:12]
        self.task: str = task
        self.state: str = "idle"
        self.plan: Optional[Dict] = None
        self.use_mock_plan: bool = use_mock_plan
        self.events: List[Dict] = []
        self.result: Optional[Dict] = None
        self._created_at: float = time.time()

    def emit(self, kind: str, **fields: Any) -> None:
        self.events.append({
            "seq": len(self.events),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            **fields,
        })

    def snapshot(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task": self.task,
            "state": self.state,
            "plan": self.plan,
            "result": self.result,
            "event_count": len(self.events),
        }

    def events_since(self, seq: int) -> List[Dict]:
        return [e for e in self.events if e["seq"] >= seq]


class SessionRunner:
    """協調 Session 生命週期、建立 AgentLoop 並執行。"""

    def __init__(
        self,
        session: Session,
        bridge: BrowserBridgeManager,
        screen_manager: Optional[ScreenManager] = None,
    ):
        self.session = session
        self.bridge = bridge
        self.screen_manager = screen_manager or ScreenManager(
            model_max_width=config.MODEL_MAX_WIDTH,
            screenshot_dir=config.SCREENSHOT_DIR,
        )

    def _make_agent_loop(self, observation_mode: str) -> AgentLoop:
        client = OllamaClient(
            host=config.OLLAMA_HOST,
            timeout=config.REQUEST_TIMEOUT,
            temperature=config.MODEL_TEMPERATURE,
        )
        if observation_mode == OBSERVATION_MODE_BROWSER:
            obs_provider = BrowserObservationProvider(
                bridge=self.bridge,
                screenshot_dir=config.SCREENSHOT_DIR,
            )
            action_exec = BrowserActionExecutor(
                bridge=self.bridge,
                action_delay=config.ACTION_DELAY,
            )
        else:
            obs_provider = None
            action_exec = None

        tool_executor = ToolExecutor(
            screen_manager=self.screen_manager,
            action_delay=config.ACTION_DELAY,
        )

        return AgentLoop(
            client=client,
            observation_provider=obs_provider,
            action_executor=action_exec,
            screen_manager=self.screen_manager,
            tool_executor=tool_executor,
            vision_model=config.VISION_MODEL,
            observation_mode=observation_mode,
            max_steps=config.MAX_STEPS,
            session_id=self.session.session_id,
        )

    async def plan_task(self, task: str) -> Dict[str, Any]:
        """產生（或載入假資料）計畫並等待使用者 approve。"""
        self.session.task = task
        self.session.state = "planning"
        self.session.emit("state", state="planning")

        if self.session.use_mock_plan:
            plan = MOCK_THSR_PLAN
            logger.info("[Session %s] 使用假資料 plan", self.session.session_id)
        else:
            # TODO: 接真正的 Ollama Planner
            plan = MOCK_THSR_PLAN
            logger.info("[Session %s] Planner 尚未接入，使用假資料 plan", self.session.session_id)

        self.session.plan = plan
        self.session.state = "awaiting_approval"
        self.session.emit("plan_ready", plan=plan)
        return plan

    async def execute_approved_plan(
        self, observation_mode: str = OBSERVATION_MODE_BROWSER
    ) -> Dict[str, Any]:
        """使用者 approve 後執行計畫。"""
        if not self.session.plan:
            return {"state": "failed", "reason": "尚無計畫"}

        self.session.state = "executing"
        self.session.emit("state", state="executing", observation_mode=observation_mode)

        loop = self._make_agent_loop(observation_mode)

        def on_step_done(step_log):
            self.session.emit(
                "step",
                step=step_log.current_step,
                action=step_log.parsed_action,
                url=step_log.current_url,
                elements_count=step_log.interactive_elements_count,
                screenshot=step_log.screenshot_path,
                ok=step_log.execution_result.get("ok") if step_log.execution_result else None,
                error=step_log.error_message or None,
            )

        # 掛 hook：每步執行完 emit 事件
        original_run = loop.run

        async def run_with_events(task, approved_plan):
            result = await original_run(task, approved_plan)
            for sl in loop.step_logs:
                on_step_done(sl)
            return result

        approved_plan = self.session.plan.get("plan", [])
        result = await run_with_events(self.session.task, approved_plan)

        self.session.result = result
        self.session.state = result.get("state", "failed")
        self.session.emit("done", **result)
        logger.info("[Session %s] 完成 state=%s reason=%s", self.session.session_id, result.get("state"), result.get("reason"))
        return result

    # 保留原有簡單截圖測試（向下相容）
    def run(self):
        screenshot_info = self.screen_manager.capture_screen()
        return {
            "image_base64": screenshot_info["image_base64"],
            "path": screenshot_info["path"],
            "scale": screenshot_info["scale"],
            "phash": screenshot_info["phash"],
        }
