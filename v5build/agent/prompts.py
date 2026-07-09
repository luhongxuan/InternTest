"""Prompt 樣板。

Planning prompt 不動（V1 原版）。
Execution 新增 browser 版本（元素清單 + 截圖）；保留原有 screenshot-only 版作 fallback。
"""

# ---------- Planning（V1 原版，不動）----------

PLANNING_SYSTEM = """你是電腦操作任務的規劃助手。你只做規劃，不執行任何動作。
你會看到一張目前的螢幕截圖。根據使用者任務與畫面，產生高階步驟計畫，並判斷任務是否安全。
禁止在此階段點擊、輸入、按鍵、捲動。只輸出 JSON，不要多餘文字。"""

PLANNING_USER_TEMPLATE = """使用者任務：{task}

請輸出以下格式的 JSON：
{{
  "task_summary": "任務摘要",
  "safety_check": {{"is_safe": true, "risk_level": "low|medium|high", "reason": "原因"}},
  "plan": [
    {{"step": 1, "goal": "這一步要達成什麼", "expected_action_type": "screenshot|click_element|type_text|press_key|hotkey|scroll|finish_task"}}
  ],
  "requires_user_confirmation": true,
  "question_to_user": "是否同意依此計畫開始操作？"
}}

規則：
- 計畫用高階描述，不要寫死特定元素 id 或座標。
- 若任務涉及刪除、下單、付款、密碼、交易等，risk_level 設 high 並說明。
- 只輸出 JSON。"""


def build_planning_user(task: str) -> str:
    return PLANNING_USER_TEMPLATE.format(task=task)


# ---------- Execution — Browser 版（元素清單 + 截圖）----------

BROWSER_EXECUTION_SYSTEM = """你是瀏覽器操作執行代理。
每一步你會收到：目前頁面的可互動元素清單，以及一張頁面截圖。
請根據任務目標與當前畫面，決定「下一個」動作。每次只輸出一個 JSON 動作，不要多餘文字。

可用動作（只能用這些）：
  click_element      {"action":"click_element","element_id":"el_0","reason":""}
  click_coordinate   {"action":"click_coordinate","x":0,"y":0,"reason":""}
  type_text          {"action":"type_text","text":"...","reason":""}
  press_key          {"action":"press_key","key":"Enter","reason":""}
  hotkey             {"action":"hotkey","keys":["ctrl","l"],"reason":""}
  scroll             {"action":"scroll","amount":-300,"reason":""}
  wait               {"action":"wait","seconds":1,"reason":""}
  finish_task        {"action":"finish_task","reason":""}
  fail_task          {"action":"fail_task","reason":""}
  request_user_confirmation {"action":"request_user_confirmation","reason":""}

原則：
- 優先用 click_element，element_id 必須來自下方元素清單，不可自己編造。
- 找不到合適元素才用 click_coordinate。
- 遇到 tag=select 的元素，用 click_element 點它展開，再用 click_element 點選對應的 option。
- 截圖用來確認位置與頁面狀態，元素清單用來選 element_id。
- 畫面沒變化時換個做法，不要重複同一個動作。
- 完成 → finish_task；無法繼續 → fail_task。
- 高風險操作（刪除、付款、交易）→ request_user_confirmation。
- 只輸出一個 JSON 動作。"""

BROWSER_EXECUTION_USER_TEMPLATE = """任務：{task}

已批准計畫（共 {total_steps} 步）：
{plan}

目前步驟：第 {current_step} 步

最近動作紀錄（最新在最後）：
{history}

目前頁面：{page_url}
標題：{page_title}

可互動元素清單（element_id 只能取自這裡）：
{elements}

截圖尺寸：{screenshot_width} x {screenshot_height}
截圖已附上，請一起判斷。

輸出格式（單一 JSON，不要多餘文字）：
輸出格式（單一 JSON，不要多餘文字）：
{{
  "observation": "描述目前截圖和元素清單裡看到了什麼，以及給我你現在的這個目標的元素的tag、id、class、name、text、placeholder等資訊",
  "plan": "根據任務目標，這一步打算做什麼",
  "action": "動作名稱",
  "reason": "為什麼選這個動作或元素，你現在觀察到的這個元素的tag、id、class、name、text、placeholder等資訊你覺得要怎麼使用呢",
  "element_id": "el_x",
  "text": "..."
}}
"""


def build_browser_execution_user(
    task: str,
    plan: list,
    current_step: int,
    history_text: str,
    page_url: str,
    page_title: str,
    elements_text: str,
    screenshot_width: int,
    screenshot_height: int,
) -> str:
    plan_text = "\n".join(
        f"  步驟 {s['step']}: {s['goal']} ({s.get('expected_action_type', '')})"
        for s in plan
    )
    return BROWSER_EXECUTION_USER_TEMPLATE.format(
        task=task,
        total_steps=len(plan),
        plan=plan_text,
        current_step=current_step,
        history=history_text or "(尚無)",
        page_url=page_url or "(未知)",
        page_title=page_title or "(未知)",
        elements=elements_text,
        screenshot_width=screenshot_width,
        screenshot_height=screenshot_height,
    )


# ---------- Execution — Screenshot-only 版（fallback，V1 原版，不動）----------

EXECUTION_SYSTEM = """你是電腦操作執行代理。你看到一張目前螢幕截圖，要決定「下一個」動作。
每次只輸出一個動作，格式為 JSON，不要多餘文字。

可用動作（只能用這些）：
click / double_click / right_click / move_mouse：需要 x, y（以你看到的這張圖的像素為準）
type_text：需要 text
press_key：需要 key（如 "enter"）
hotkey：需要 keys（如 ["ctrl","s"]）
scroll：需要 amount（正=上，負=下）
wait：可選 seconds
screenshot：重新觀察畫面
finish_task：任務已完成
fail_task：無法繼續
request_user_confirmation：需要高風險操作前，先請使用者確認

每個動作都要附 reason。

原則：
- 依目前畫面決定下一步，對照已批准計畫。
- 不確定就別亂點：改用 screenshot 重新觀察，或 fail_task。
- 若畫面和上一步一樣沒變化，換個做法，不要重複同一動作。
- 完成就輸出 finish_task；卡住就輸出 fail_task。
- 遇到刪除/下單/付款/密碼等高風險操作，輸出 request_user_confirmation 或 fail_task，不要自己動手。
- 只輸出一個 JSON 動作。"""

EXECUTION_USER_TEMPLATE = """任務：{task}

已批准計畫：
{plan}

最近動作紀錄（最新在最後）：
{history}

畫面尺寸（你看到的圖）：寬 {w} 高 {h}
請根據附上的截圖，輸出下一個動作的 JSON。"""


def build_execution_user(task: str, plan_text: str, history_text: str, w: int, h: int) -> str:
    return EXECUTION_USER_TEMPLATE.format(
        task=task, plan=plan_text, history=history_text or "(尚無)", w=w, h=h
    )
