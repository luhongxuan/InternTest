"""全域設定。所有可調參數集中在此，避免散落各檔。"""

# --- Ollama ---
OLLAMA_HOST = "http://localhost:11434"
# 第一版 Planner 與 Executor 都用同一顆 vision 模型即可（規劃時也看得到畫面）。
# 若想用純文字模型做 Planner，可改成 "qwen2.5:7b"，但那樣 Planner 就看不到螢幕。
PLANNER_MODEL = "qwen2.5vl:7b"
EXECUTOR_MODEL = "qwen2.5vl:7b"
REQUEST_TIMEOUT = 180          # 單次模型呼叫逾時秒數
MODEL_TEMPERATURE = 0.2        # 低溫度，讓輸出穩定、少發散

# --- 螢幕 / 截圖 ---
# mss 的 monitor index：0 = 全部螢幕合併，1 = 主螢幕，2 = 第二螢幕...
MONITOR_INDEX = 1
# 送給模型前，把截圖等比例縮到寬度不超過此值，降低 VRAM 壓力並穩定 grounding。
MODEL_MAX_WIDTH = 1280

# --- 執行迴圈安全上限 ---
MAX_STEPS = 20                 # 單一任務最多執行步數
MAX_SAME_ACTION_REPEAT = 3     # 同一個 action 連續重複幾次就中止
MAX_NO_CHANGE = 3              # 畫面連續幾次沒變化就中止
ACTION_DELAY = 0.6             # 每個動作後等待秒數，讓畫面有時間反應
HISTORY_WINDOW = 5             # 送給模型的「最近動作」筆數

# --- 路徑 ---
LOG_DIR = "logs"
SCREENSHOT_DIR = "screenshots"
