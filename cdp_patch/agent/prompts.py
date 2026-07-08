"""Prompt 樣板。

刻意寫短：本地 7B vision 模型對長 prompt 很敏感，越長越容易發散、
忽略歷史、產生 reasoning 與 action 不一致。因此只給最必要的規則。
所有 prompt 都要求「只輸出 JSON」。
"""

# ---------- Planning ----------

PLANNING_SYSTEM = """你是電腦操作任務的規劃助手。你只做規劃，不執行任何動作。
你會看到一張目前的螢幕截圖。根據使用者任務與畫面，產生高階步驟計畫，並判斷任務是否安全。
禁止在此階段點擊、輸入、按鍵、捲動。只輸出 JSON，不要多餘文字。"""

PLANNING_USER_TEMPLATE = """使用者任務：{task}

請輸出以下格式的 JSON：
{{
  "task_summary": "任務摘要",
  "safety_check": {{"is_safe": true, "risk_level": "low|medium|high", "reason": "原因"}},
  "plan": [
    {{"step": 1, "goal": "這一步要達成什麼", "expected_action_type": "screenshot|click|type_text|press_key|hotkey|scroll|finish_task"}}
  ],
  "requires_user_confirmation": true,
  "question_to_user": "是否同意依此計畫開始操作？"
}}

規則：
- 計畫用高階描述，不要寫死特定軟體按鈕座標。
- 若任務涉及刪除、下單、付款、密碼、交易等，risk_level 設 high 並說明。
- 只輸出 JSON。"""


def build_planning_user(task: str) -> str:
    return PLANNING_USER_TEMPLATE.format(task=task)


# ---------- Execution ----------

EXECUTION_SYSTEM = """你是網頁操作執行代理。你會看到「一張截圖」和「一份可互動元素清單」，
兩者一起判斷，決定「下一個」動作。每次只輸出一個 JSON 動作，不要多餘文字。

可用動作（只能用這些）：
click_element：點清單裡的某個元素，需要 element_id。格式 {"action":"click_element","element_id":0,"reason":""}
type_in_element：在某元素輸入文字，需要 element_id 與 text。格式 {"action":"type_in_element","element_id":0,"text":"","reason":""}
scroll：捲動，需要 amount（正=上，負=下）
finish_task：任務已完成
fail_task：無法繼續

原則：
- 優先用 click_element / type_in_element，element_id 一定要來自清單，不可自己編。
- 用截圖確認元素位置與畫面狀態，用清單挑正確的 id。
- 不確定就 fail_task，不要亂點。
- 完成輸出 finish_task。只輸出一個 JSON 動作。"""

EXECUTION_USER_TEMPLATE = """任務：{task}

計畫：
{plan}

最近動作紀錄（最新在最後）：
{history}

可互動元素清單（element_id 取自這裡）：
{elements}

請一起看附上的截圖與上面清單，輸出下一個動作的 JSON。"""


def format_elements(elements) -> str:
    """把元素清單印成模型好讀的一行一筆。"""
    if not elements:
        return "(無)"
    lines = []
    for i, e in enumerate(elements):
        name = e.get("name", "") or "(無文字)"
        role = e.get("role") or e.get("tag", "")
        lines.append(f'#{i} {role} "{name}" @({e.get("cx")},{e.get("cy")})')
    return "\n".join(lines)


def build_execution_user(task: str, plan_text: str, history_text: str, elements) -> str:
    return EXECUTION_USER_TEMPLATE.format(
        task=task, plan=plan_text, history=history_text or "(尚無)",
        elements=format_elements(elements),
    )
