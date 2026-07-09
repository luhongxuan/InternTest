"""FastAPI 後端

新增：
  WebSocket /ws/browser  — Extension bridge 連線端點
  POST /task/plan        — 產生計畫
  POST /task/approve     — Approve 並開始執行
  GET  /session/{id}/status
  GET  /session/{id}/events?since=N
  GET  /health

保留：
  POST /test_screenshot  — 原有截圖測試
"""

import asyncio
import logging
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from agent.screen import ScreenManager
from backend.session import Session, SessionRunner
from browser.observation_provider import BrowserBridgeManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Local Computer Use Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全域共用的 bridge（一個 server 只管一條 Extension 連線）
bridge = BrowserBridgeManager()

# 簡易 session 儲存（第一版 in-memory）
_sessions: Dict[str, Session] = {}
_runners: Dict[str, SessionRunner] = {}


# ---------------------------------------------------------------------------
# WebSocket bridge endpoint
# ---------------------------------------------------------------------------

@app.websocket(config.WS_BROWSER_PATH)
async def ws_browser_endpoint(websocket: WebSocket):
    """Extension bridge 連線端點。
    Extension 的 bridge_client.js 連到此 endpoint，
    Python backend 透過 BrowserBridgeManager 送命令、收結果。
    """
    logger.info("[Server] Extension WebSocket 連線嘗試")
    await bridge.accept(websocket)


# ---------------------------------------------------------------------------
# Task API
# ---------------------------------------------------------------------------

class PlanRequest(BaseModel):
    task: str
    use_mock_plan: bool = True   # 第一版預設用假資料 plan


class ApproveRequest(BaseModel):
    session_id: str
    observation_mode: str = "browser"   # "browser" | "screenshot"


@app.post("/task/plan")
async def plan_task(req: PlanRequest):
    """產生計畫並等待 approve。"""
    session = Session(task=req.task, use_mock_plan=req.use_mock_plan)
    screen = ScreenManager(
        model_max_width=config.MODEL_MAX_WIDTH,
        screenshot_dir=config.SCREENSHOT_DIR,
    )
    runner = SessionRunner(session=session, bridge=bridge, screen_manager=screen)
    _sessions[session.session_id] = session
    _runners[session.session_id] = runner

    plan = await runner.plan_task(req.task)
    return {
        "session_id": session.session_id,
        "plan": plan,
        "status": session.snapshot(),
    }


@app.post("/task/approve")
async def approve_task(req: ApproveRequest):
    """使用者 approve 後開始執行（背景 asyncio task）。"""
    session = _sessions.get(req.session_id)
    runner = _runners.get(req.session_id)
    if not session or not runner:
        raise HTTPException(status_code=404, detail="session not found")
    if session.state not in ("awaiting_approval",):
        raise HTTPException(status_code=409, detail=f"session state={session.state}，無法 approve")

    # 背景執行，不阻塞 HTTP response
    asyncio.create_task(runner.execute_approved_plan(req.observation_mode))
    return {"session_id": session.session_id, "status": session.snapshot()}


@app.get("/session/{session_id}/status")
def get_session_status(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session.snapshot()


@app.get("/session/{session_id}/events")
def get_session_events(session_id: str, since: int = 0):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {"events": session.events_since(since), "next": len(session.events)}


# ---------------------------------------------------------------------------
# 原有端點（保留，不動）
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "bridge_connected": bridge.is_connected,
    }


@app.post("/test_screenshot")
def test_screenshot():
    screen_manager = ScreenManager()
    runner = SessionRunner(Session(), bridge=bridge, screen_manager=screen_manager)
    return runner.run()
