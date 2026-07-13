"""FastAPI 後端

端點：
  GET  /health                         — 健康 + bridge 連線狀態
  POST /task/plan     {task}           — 產生計畫
  POST /task/approve  {session_id, observation_mode}  — 背景執行
  GET  /session/{id}/status            — 狀態快照
  GET  /session/{id}/events?since=N    — 增量事件（前端輪詢）
  POST /test_screenshot                — 原有截圖測試（向下相容）
  WS   /ws/browser                     — Extension bridge
"""

import asyncio
import logging
from typing import Dict

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from agent.screen import ScreenManager
from backend.session import Session, SessionRunner
from browser.observation_provider import BrowserBridgeManager

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Local Computer Use Agent Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bridge = BrowserBridgeManager()
_sessions: Dict[str, Session] = {}
_runners: Dict[str, SessionRunner] = {}


# ---------- WebSocket bridge ----------

@app.websocket(config.WS_BROWSER_PATH)
async def ws_browser_endpoint(websocket: WebSocket):
    await bridge.accept(websocket)


# ---------- Task API ----------

class PlanRequest(BaseModel):
    task: str
    use_mock_plan: bool = True


class ApproveRequest(BaseModel):
    session_id: str
    observation_mode: str = "browser"


@app.post("/task/plan")
async def plan_task(req: PlanRequest):
    session = Session(task=req.task, use_mock_plan=req.use_mock_plan)
    runner = SessionRunner(session=session, bridge=bridge)
    _sessions[session.session_id] = session
    _runners[session.session_id] = runner
    plan = await runner.plan_task(req.task)
    return {"session_id": session.session_id, "plan": plan, "status": session.snapshot()}


@app.post("/task/approve")
async def approve_task(req: ApproveRequest):
    session = _sessions.get(req.session_id)
    runner = _runners.get(req.session_id)
    if not session or not runner:
        raise HTTPException(404, "session not found")
    asyncio.create_task(runner.execute_approved_plan(req.observation_mode))
    return {"session_id": session.session_id, "status": session.snapshot()}


@app.get("/session/{session_id}/status")
def get_status(session_id: str):
    s = _sessions.get(session_id)
    if not s:
        raise HTTPException(404, "session not found")
    return s.snapshot()


@app.get("/session/{session_id}/events")
def get_events(session_id: str, since: int = 0):
    s = _sessions.get(session_id)
    if not s:
        raise HTTPException(404, "session not found")
    return {"events": s.events_since(since), "next": len(s.events)}


# ---------- 原有端點 ----------

@app.get("/health")
def health():
    return {"status": "ok", "bridge_connected": bridge.is_connected}


@app.post("/test_screenshot")
def test_screenshot():
    screen = ScreenManager()
    session = Session()
    runner = SessionRunner(session=session, bridge=bridge)
    return runner.run_screenshot_test()
