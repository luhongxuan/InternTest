from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.screen import ScreenManager
from backend.session import Session, SessionRunner

app = FastAPI(title = "Local Computer Use Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/test_screenshot")
def test_screenshot():
    screen_manager = ScreenManager()
    runner = SessionRunner(Session(), screen_manager)
    temp = runner.run()
    return temp