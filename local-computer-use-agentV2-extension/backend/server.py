"""FastAPI 後端：Extension 前端透過這些 API 控制 Agent。

端點：
  GET  /health                      健康檢查
  POST /plan            {task, max_steps?}   -> 產生計畫（含安全檢查）
  POST /session/{id}/revise  {note}          -> 依修改意見重新規劃
  POST /session/{id}/approve                 -> 背景執行緒開始執行
  POST /session/{id}/cancel                  -> 取消
  POST /session/{id}/confirm {approved}      -> 回覆待確認的高風險動作
  GET  /session/{id}/status                  -> 目前狀態快照
  GET  /session/{id}/events?since=N          -> 增量事件（前端輪詢）
  GET  /session/{id}/screenshot              -> 最新 debug 截圖(png)

設計重點：
- 執行迴圈跑在背景執行緒，前端只要輪詢 status / events，即使側邊欄關掉再開
  也能重新接上同一個 session。
- 需要確認的高風險動作會讓迴圈暫停在 pending_confirm，前端跳出確認框後
  POST /confirm 才會繼續。
"""

import threading
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
from agent.logger import RunLogger
from agent.model_client import OllamaClient
from agent.planner import Planner
from agent.screen import ScreenManager
from agent.tools import ToolExecutor
from backend.session import Session, SessionRunner

app = FastAPI(title="Local Computer Use Agent Backend")

# 本地開發：只綁 localhost，允許 extension 跨來源呼叫。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class _Deps:
    """延遲初始化的共用資源（ScreenManager 需要有顯示器，故不在 import 時建立）。"""
    def __init__(self):
        self._lock = threading.Lock()
        self.client: Optional[OllamaClient] = None
        self.screen: Optional[ScreenManager] = None
        self.tools: Optional[ToolExecutor] = None
        self.logger: Optional[RunLogger] = None

    def ensure(self):
        with self._lock:
            if self.client is None:
                self.client = OllamaClient(config.OLLAMA_HOST, config.REQUEST_TIMEOUT,
                                           config.MODEL_TEMPERATURE)
            if self.screen is None:
                self.screen = ScreenManager(config.MONITOR_INDEX, config.MODEL_MAX_WIDTH,
                                            config.SCREENSHOT_DIR)
                self.tools = ToolExecutor(self.screen, config.ACTION_DELAY)
            if self.logger is None:
                self.logger = RunLogger(config.LOG_DIR)
        return self


deps = _Deps()
SESSIONS: Dict[str, Session] = {}
_sessions_lock = threading.Lock()


class PlanReq(BaseModel):
    task: str
    max_steps: Optional[int] = None


class ReviseReq(BaseModel):
    note: str


class ConfirmReq(BaseModel):
    approved: bool


def _get(session_id: str) -> Session:
    with _sessions_lock:
        s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(404, "session not found")
    return s


@app.get("/health")
def health():
    return {"ok": True, "sessions": len(SESSIONS)}


@app.post("/plan")
def plan(req: PlanReq):
    if not req.task.strip():
        raise HTTPException(400, "task 不可為空")
    d = deps.ensure()
    planner = Planner(d.client, d.screen, config.PLANNER_MODEL, d.logger)
    session = Session(req.task.strip(), req.max_steps or config.MAX_STEPS)
    plan_obj, msg = planner.make_plan(session.task)
    if plan_obj is None:
        raise HTTPException(422, f"規劃失敗：{msg}")
    session.plan = plan_obj
    session.state = session.state.__class__.AWAITING_USER_APPROVAL
    session.latest_screenshot = plan_obj.get("_screenshot_path")
    with _sessions_lock:
        SESSIONS[session.id] = session
    return {"session_id": session.id, "plan": plan_obj, "status": session.snapshot()}


@app.post("/session/{session_id}/revise")
def revise(session_id: str, req: ReviseReq):
    s = _get(session_id)
    d = deps.ensure()
    planner = Planner(d.client, d.screen, config.PLANNER_MODEL, d.logger)
    plan_obj, msg = planner.make_plan(s.task, revise_note=req.note)
    if plan_obj is None:
        raise HTTPException(422, f"重新規劃失敗：{msg}")
    s.plan = plan_obj
    return {"session_id": s.id, "plan": plan_obj, "status": s.snapshot()}


@app.post("/session/{session_id}/approve")
def approve(session_id: str):
    s = _get(session_id)
    if s._thread and s._thread.is_alive():
        raise HTTPException(409, "此 session 已在執行中")
    d = deps.ensure()
    runner = SessionRunner(s, d.client, d.screen, d.tools, d.logger, config,
                           config.EXECUTOR_MODEL)
    t = threading.Thread(target=runner.run, daemon=True)
    s._thread = t
    t.start()
    return {"session_id": s.id, "status": s.snapshot()}


@app.post("/session/{session_id}/cancel")
def cancel(session_id: str):
    s = _get(session_id)
    s.request_cancel()
    return {"session_id": s.id, "status": s.snapshot()}


@app.post("/session/{session_id}/confirm")
def confirm(session_id: str, req: ConfirmReq):
    s = _get(session_id)
    if not s.pending_confirm:
        raise HTTPException(409, "目前沒有待確認的動作")
    s.answer_confirm(req.approved)
    return {"session_id": s.id, "approved": req.approved, "status": s.snapshot()}


@app.get("/session/{session_id}/status")
def status(session_id: str):
    return _get(session_id).snapshot()


@app.get("/session/{session_id}/events")
def events(session_id: str, since: int = 0):
    s = _get(session_id)
    return {"events": s.events_since(since), "next": len(s.events)}


@app.get("/session/{session_id}/screenshot")
def screenshot(session_id: str):
    s = _get(session_id)
    if not s.latest_screenshot:
        raise HTTPException(404, "尚無截圖")
    return FileResponse(s.latest_screenshot, media_type="image/png")
