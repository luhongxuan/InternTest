# Extension 版本 — 使用說明

架構：**Chrome Extension(前端控制台) + 本地 Python FastAPI 後端(實際操作)**。

Extension 只是 UI:輸入任務、看計畫、approve/revise/cancel、看即時狀態與截圖。
真正的滑鼠鍵盤、截圖、Ollama 推論都在本地 Python 後端執行,所以**能控制整個桌面**,不只瀏覽器。

```
[Chrome 側邊欄 UI]  --fetch-->  [FastAPI localhost:8756]  -->  [pyautogui + mss + Ollama]
        ↑ 輪詢 status/events                背景執行緒跑 Agent 迴圈
```

> 重要:瀏覽器 extension 本身無法控制 OS 滑鼠鍵盤,那是後端 Python 做的。
> Extension 與後端是分開的兩個東西,必須兩個都啟動。

---

## 一、啟動後端

```bash
pip install -r requirements.txt
ollama pull qwen2.5vl:7b        # 若尚未下載
python run_backend.py
```

看到 `http://127.0.0.1:8756` 就代表後端起來了。先用瀏覽器開 `http://127.0.0.1:8756/health` 應回 `{"ok": true}`。

---

## 二、載入 Extension

1. Chrome 開 `chrome://extensions`。
2. 右上角開啟「開發人員模式」。
3. 點「載入未封裝項目」,選這個專案的 `extension/` 資料夾。
4. 釘選圖示,點一下即開啟右側側邊欄。

側邊欄右上角會顯示「後端已連線 / 未連線」。若顯示未連線,確認 `run_backend.py` 有在跑。

---

## 三、操作流程

1. 在側邊欄輸入任務、設定最大步數 → 按「產生計畫」。
2. 檢視計畫與安全檢查:
   - **Approve 並執行**:背景開始操作,側邊欄即時顯示狀態、最新截圖與事件。
   - **修改**:輸入修改意見重新規劃。
   - **取消**:結束此任務。
3. 執行中若遇到高風險動作(例如關閉視窗的快捷鍵),側邊欄會跳出確認框,按「允許 / 拒絕」。
4. 任務結束顯示最終狀態(completed / failed / cancelled)。

因為執行迴圈在後端背景跑,**側邊欄關掉再開也能重新接回同一個任務**。

---

## 四、API(給你之後擴充或接其他前端)

| Method | Path | 說明 |
|---|---|---|
| GET | `/health` | 健康檢查 |
| POST | `/plan` | body `{task, max_steps?}` → 產生計畫 |
| POST | `/session/{id}/revise` | body `{note}` → 依修改意見重規劃 |
| POST | `/session/{id}/approve` | 開始背景執行 |
| POST | `/session/{id}/cancel` | 取消 |
| POST | `/session/{id}/confirm` | body `{approved}` → 回覆待確認動作 |
| GET | `/session/{id}/status` | 狀態快照 |
| GET | `/session/{id}/events?since=N` | 增量事件(前端輪詢) |
| GET | `/session/{id}/screenshot` | 最新 debug 截圖 |

---

## 五、安全與限制(務必看)

- **緊急中止**:執行中滑鼠移到螢幕**左上角**觸發 FAILSAFE 立即停止;或按側邊欄「停止任務」。
- 後端只綁 `127.0.0.1`,不對外開放。CORS 目前為開發用的寬鬆設定,若要更嚴,把 `backend/server.py` 的 `allow_origins` 改成你的 extension id(`chrome-extension://<id>`)。
- 因為後端控制整個桌面,執行期間游標可能點到瀏覽器本身。請讓目標視窗保持在前景,並在**測試環境 / 非正式帳號**執行。
- 危險關鍵字(刪除、下單、付款、密碼、交易…)會被標高風險;部分危險快捷鍵(Win+R、工作管理員)直接封鎖,關閉視窗類快捷鍵要求二次確認。這是第一層務實防護,**不是完整沙箱**。
- **絕對不要**對接真實證券交易系統或任何不可逆環境。

---

## 六、如果你其實只需要控制「瀏覽器內的網頁」

那更好的做法是純 extension 用 `chrome.debugger`(CDP)的 `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent`,點擊依真實 DOM 座標,比截圖 + 7B grounding 穩非常多,而且不需要 pyautogui。這版沒做這條路;若目標是內部網頁系統,值得改走 CDP 版,我可以另外給你。

---

## 檔案結構(Extension 版新增部分)

```
├── run_backend.py           # 啟動後端
├── backend/
│   ├── server.py            # FastAPI 端點
│   └── session.py           # 背景執行緒 + 事件 + 確認機制
├── extension/
│   ├── manifest.json        # MV3
│   ├── background.js        # 開側邊欄
│   ├── sidepanel.html/.js   # 控制台 UI
│   └── styles.css
└── agent/  ...              # 與 CLI 版共用的核心(截圖/工具/安全/模型)
```

CLI 版(`python main.py`)仍可獨立使用,兩者共用 `agent/` 核心。
