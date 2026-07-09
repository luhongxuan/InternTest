"""全域設定 — 常數集中管理，避免 magic string 散落各處。"""

# --- Ollama ---
OLLAMA_HOST = "http://localhost:11434"
PLANNER_MODEL = "qwen2.5:14b"
VISION_MODEL = "qwen2.5vl:7b"
REQUEST_TIMEOUT = 180
MODEL_TEMPERATURE = 0.2

# --- Screenshot ---
MODEL_MAX_WIDTH = 1028

# --- Execution ---
ACTION_DELAY = 0.6
HISTORY_WINDOW = 5
MAX_STEPS = 20

# --- File paths ---
LOG_DIR = "logs"
SCREENSHOT_DIR = "screenshots"

# --- Backend ---
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000

# --- WebSocket bridge ---
WS_BROWSER_PATH = "/ws/browser"
WS_COMMAND_TIMEOUT_SEC = 30   # 等待 extension 回覆的最長秒數
