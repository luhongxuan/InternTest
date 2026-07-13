"""Session — 單一任務生命週期管理。

整合 V1 的 RunLogger / TaskState / safety 與 v4 的 browser 模式。
每個 Session 有一個獨立的 RunLogger，logs/ 目錄下每次執行一個 .jsonl 檔。
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import config
from agent.agent_loop import AgentLoop, OBSERVATION_MODE_BROWSER, OBSERVATION_MODE_SCREENSHOT
from agent.logger import RunLogger
from agent.model_client import OllamaClient
from agent.safety import scan_task_risk
from agent.screen import ScreenManager
from agent.state import TaskState
from agent.tools import ToolExecutor
from browser.action_executor import BrowserActionExecutor
from browser.observation_provider import BrowserBridgeManager, BrowserObservationProvider

module_logger = logging.getLogger(__name__)

# 第一版假資料 plan（Planner 接入前用）
MOCK_THSR_PLAN = {
  "task_summary": "查詢台灣高鐵從台北到台中，明天上午 09:00 左右出發的班次資訊。",
  "safety_check": {
    "is_safe": True,
    "risk_level": "low",
    "reason": "此任務只涉及開啟高鐵查詢頁面並查詢公開班次資訊，不包含登入帳號、輸入個資、付款、訂票或送出交易。"
  },
  "plan": [
    {
      "step": 1,
      "goal": "觀察頁面，確認目前已進入高鐵班次查詢頁面，並找到出發站、抵達站、日期、時間與查詢按鈕等可互動元素。",
      "expected_action_type": "screenshot"
    },
    {
      "step": 2,
      "goal": "操作出發站的下拉式選單，準備選擇台北作為出發站。",
      "expected_action_type": "select_element"
    },
    {
      "step": 3,
      "goal": "操作抵達站的下拉式選單，準備選擇台中作為抵達站。",
      "expected_action_type": "select_element"
    },
    {
      "step": 4,
      "goal": "點擊日期欄位，選擇明天的日期。",
      "expected_action_type": "click"
    },
    {
      "step": 5,
      "goal": "點擊時間欄位，輸入或選擇上午 09:00 左右的出發時間。",
      "expected_action_type": "click"
    },
    {
      "step": 6,
      "goal": "在時間欄位輸入 09:00，或選擇接近 09:00 的時間選項。",
      "expected_action_type": "type_text"
    },
    {
      "step": 7,
      "goal": "點擊查詢按鈕，送出班次查詢。",
      "expected_action_type": "click"
    },
    {
      "step": 8,
      "goal": "觀察查詢結果頁面，確認是否已顯示台北到台中、明天上午 09:00 左右出發的高鐵班次。",
      "expected_action_type": "screenshot"
    },
    {
      "step": 9,
      "goal": "如果畫面已顯示符合條件的班次資訊，整理目前查詢結果並結束任務。",
      "expected_action_type": "finish_task"
    }
  ]
}


class Session:
    """單一任務狀態容器。"""

    def __init__(self, task: str = "", use_mock_plan: bool = True):
        self.session_id: str = uuid.uuid4().hex[:12]
        self.task: str = task
        self.state: str = TaskState.IDLE.value
        self.plan: Optional[Dict] = None
        self.use_mock_plan: bool = use_mock_plan
        self.result: Optional[Dict] = None
        self.events: List[Dict] = []
        # 每個 Session 獨立一個 logger（logs/run_{ts}.jsonl）
        self.run_logger: RunLogger = RunLogger(config.LOG_DIR)
        self._created_at: float = time.time()

    def emit(self, kind: str, **fields: Any) -> None:
        record = {
            "seq": len(self.events),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            **fields,
        }
        self.events.append(record)
        self.run_logger.log(kind, **fields)   # 同步寫進 JSONL

    def snapshot(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task": self.task,
            "state": self.state,
            "plan": self.plan,
            "result": self.result,
            "log_path": self.run_logger.path,
            "event_count": len(self.events),
        }

    def events_since(self, seq: int) -> List[Dict]:
        return [e for e in self.events if e["seq"] >= seq]

    def close(self) -> None:
        self.run_logger.close()


class SessionRunner:
    """協調 Session 生命週期，建立 AgentLoop 並執行。"""

    def __init__(self, session: Session, bridge: BrowserBridgeManager):
        self.session = session
        self.bridge = bridge
        self._screen = ScreenManager(
            model_max_width=config.MODEL_MAX_WIDTH,
            screenshot_dir=config.SCREENSHOT_DIR,
        )

    async def plan_task(self, task: str) -> Dict[str, Any]:
        """產生計畫（第一版用假資料，後續換 Planner）。"""
        s = self.session
        s.task = task
        s.state = TaskState.PLANNING.value
        s.emit("state", state=s.state)

        # 關鍵字安全掃描（來自 V1 safety）
        risk = scan_task_risk(task)
        s.run_logger.log("safety_scan", task=task, **risk)

        if s.use_mock_plan:
            plan = MOCK_THSR_PLAN
        else:
            # TODO: 接真正的 Ollama Planner
            plan = MOCK_THSR_PLAN

        # 若關鍵字掃描發現高風險，疊加到 plan 的 safety_check
        if not risk["is_safe"]:
            plan["safety_check"]["is_safe"] = False
            plan["safety_check"]["risk_level"] = "high"
            plan["safety_check"]["reason"] = (
                plan["safety_check"]["reason"] + f" | 系統掃描：{risk['reason']}"
            ).strip(" |")

        s.plan = plan
        s.state = TaskState.AWAITING_USER_APPROVAL.value
        s.emit("plan_ready", plan=plan, safety=risk)
        return plan

    async def execute_approved_plan(
        self, observation_mode: str = OBSERVATION_MODE_BROWSER
    ) -> Dict[str, Any]:
        """使用者 approve 後，建立 AgentLoop 並執行。"""
        s = self.session
        if not s.plan:
            return {"state": "failed", "reason": "尚無計畫"}

        s.state = TaskState.EXECUTING.value
        s.emit("state", state=s.state, observation_mode=observation_mode)

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
            act_executor = BrowserActionExecutor(
                bridge=self.bridge,
                logger=s.run_logger,
                action_delay=config.ACTION_DELAY,
            )
        else:
            obs_provider = None
            act_executor = None

        tool_executor = ToolExecutor(
            screen_manager=self._screen,
            action_delay=config.ACTION_DELAY,
        )

        def confirm_fn(message: str) -> bool:
            """非同步環境下的 confirm：記錄到 log，預設拒絕（Extension 版需另接前端確認）。"""
            s.emit("await_confirmation", message=message)
            module_logger.warning("[Session %s] 需要確認：%s（自動拒絕）", s.session_id, message)
            return False

        loop = AgentLoop(
            client=client,
            screen_manager=self._screen,
            tool_executor=tool_executor,
            model=config.EXECUTOR_MODEL,
            run_logger=s.run_logger,
            cfg=config,
            confirm_fn=confirm_fn,
            observation_provider=obs_provider,
            action_executor=act_executor,
            observation_mode=observation_mode,
        )

        result = await loop.run(s.task, s.plan)

        outcome = {
            "state": result.state.value,
            "reason": result.reason,
            "steps": result.steps,
            "log_path": s.run_logger.path,
        }
        s.result = outcome
        s.state = result.state.value
        s.emit("done", **outcome)
        s.close()
        return outcome

    def run_screenshot_test(self) -> Dict[str, Any]:
        """保留原有截圖測試端點的相容方法。"""
        info = self._screen.capture_screen()
        return {
            "image_base64": info["image_base64"],
            "path": info["path"],
            "scale": info["scale"],
            "phash": info["phash"],
        }
