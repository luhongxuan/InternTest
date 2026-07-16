# 本地端通用 Computer Use Agent（MVP）

一個完全在本地端執行的通用電腦操作 Agent。使用者用自然語言描述任務，Agent 先觀察螢幕、產生高階計畫並請使用者確認，approve 後才用滑鼠鍵盤實際操作。所有模型推論走 **Ollama 本地模型**，不使用任何雲端 API。

不綁定任何特定軟體：沒有記事本專用流程、沒有 DOM selector、沒有寫死的按鈕。只提供通用工具（click / type_text / press_key / hotkey / scroll / screenshot / wait 等），由 vision 模型看畫面決定下一步。

---

## 這一版能做什麼、不能做什麼

**能做：** 建立一套可執行、可觀察、可擴充的框架 — 完整的 Planning→Approval→Execution 狀態機、嚴格 action schema、逐步 JSON log、重複/無變化偵測、危險操作攔截。簡單、目標明顯的任務（點一個清楚的輸入框、輸入文字、點桌面上明顯圖示）有機會完成。

**不能做（誠實說）：** 本地 7B vision 模型的視覺 grounding 與多步規劃能力有限，不要期待它像 Claude Computer Use / OpenAI Operator 一樣穩定。複雜、多步、畫面密集的任務常會卡住、點錯位置或提早 fail_task。這是**模型能力天花板**，不是 prompt 沒調好 — 這版的價值在於「框架與安全機制」，模型換更強時可直接受益。

---

## 安裝

需求：Windows、Python 3.10+、已安裝並執行中的 Ollama。

```bash
pip install -r requirements.txt
```

確認 Ollama 模型已就緒：

```bash
ollama list
# 若沒有，先拉下來：
ollama pull qwen2.5vl:7b
ollama pull qwen2.5:7b
```

確認 Ollama 服務有在跑（預設 http://localhost:11434）：

```bash
ollama ps
```

---

## 執行

```bash
python main.py
# 或直接帶任務與步數上限
python main.py --task "點擊畫面中的搜尋框並輸入 hello" --max-steps 15
```

流程：
1. 輸入任務 → Agent 截圖並產生計畫。
2. 看到計畫與安全檢查後選擇：`[A]` approve、`[R]` 修改、`[C]` 取消。
3. approve 後才開始操作。每一步會印出模型的 action 與執行結果。
4. 結束後印出最終狀態與 log 路徑。

---

## 建議的第一個測試任務

由簡入難，先確認 grounding 準不準：

1. 開一個記事本，任務：「在目前這個視窗裡點一下輸入區，然後輸入 hello world」。
2. 「在目前焦點的位置輸入這段文字：測試中文輸入」。
3. 開好瀏覽器停在有搜尋框的頁面，任務：「點畫面上的搜尋框，輸入 ollama」。
4. 「點擊桌面上的資源回收筒圖示」（只點擊、不刪東西）。
5. 「觀察目前畫面，如果已經有記事本開著並且有文字，就回報任務完成」。

先跑 1、2 校正座標；若點擊系統性偏移，多半是縮放換算或多螢幕 offset，對照 `screenshots/` 裡的 debug 截圖即可判斷。

---

## 設定（`config.py`）

`MONITOR_INDEX`（1=主螢幕）、`MODEL_MAX_WIDTH`（送模型前縮圖寬度）、`MAX_STEPS`、`MAX_SAME_ACTION_REPEAT`、`MAX_NO_CHANGE`、`ACTION_DELAY`、模型名稱等都在這裡。

---

## 安全提醒（務必看）

- **緊急中止**：執行期間把滑鼠快速移到螢幕**左上角**即可觸發 pyautogui FAILSAFE 立刻停止；或按 Ctrl+C。
- approve 前，程式**不會**做任何改變電腦狀態的操作。
- 涉及刪除、下單、付款、密碼、交易、關機、shell 指令等關鍵字的任務會被標為高風險；部分危險快捷鍵（Win+R、工作管理員等）會被直接封鎖，關閉視窗類快捷鍵會要求二次確認。
- 這些是**第一層務實防護，不是完整沙箱**。請務必在**測試環境 / 非正式帳號**執行，**絕對不要**對接真實證券交易系統或任何會造成不可逆後果的環境。
- log 會記下每一步的模型原始輸出、動作、座標與結果（`logs/*.jsonl`），方便事後稽核與展示。

---

## 檔案結構

```
local-computer-use-agent/
├── main.py              # CLI：任務輸入、計畫確認、執行、結果
├── config.py            # 所有可調參數
├── agent/
│   ├── state.py         # 任務狀態機
│   ├── schemas.py       # 嚴格 action / plan 驗證（白名單）
│   ├── safety.py        # 危險關鍵字、快捷鍵攔截、重複/無變化偵測
│   ├── screen.py        # 截圖、縮放、座標換算、畫面雜湊
│   ├── model_client.py  # Ollama 呼叫（強制 JSON 輸出）
│   ├── prompts.py       # Planning / Execution 短 prompt
│   ├── planner.py       # 觀察 + 規劃（不操作）
│   ├── agent_loop.py    # 執行迴圈 + 停止條件
│   └── logger.py        # JSONL log
├── logs/
├── screenshots/
└── requirements.txt
```

---

## 已知限制與下一步

- 座標 grounding 依賴模型對縮圖的判讀，複雜畫面誤差大。可考慮之後加入 set-of-marks（在截圖上標號可點元素）降低對純座標的依賴。
- 「action 偏離已批准計畫」目前只做高風險動作攔截，沒有做語意層級的偏離判斷（7B 模型下不可靠）。
- 換上更強的本地 vision 模型（例如更大參數或專為 GUI grounding 微調的模型）時，架構、安全機制、log 都可沿用，直接受益。
