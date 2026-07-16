"""全域設定 — 所有可調參數集中在此，避免 magic string 散落各處。"""

# --- Ollama ---
OLLAMA_HOST = "http://localhost:11434"
PLANNER_MODEL = "qwen2.5vl:7b"
EXECUTOR_MODEL = "qwen2.5vl:7b"
REQUEST_TIMEOUT = 180
MODEL_TEMPERATURE = 0.2

# --- 螢幕 / 截圖 ---
MONITOR_INDEX = 1
MODEL_MAX_WIDTH = 1280

# --- 執行迴圈安全上限 ---
MAX_STEPS = 20
MAX_SAME_ACTION_REPEAT = 3
MAX_NO_CHANGE = 3
ACTION_DELAY = 0.6
HISTORY_WINDOW = 5

# --- 路徑 ---
LOG_DIR = "logs"
SCREENSHOT_DIR = "screenshots"

# --- Backend（Extension 版）---
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000

# --- WebSocket bridge ---
WS_BROWSER_PATH = "/ws/browser"
WS_COMMAND_TIMEOUT_SEC = 30
