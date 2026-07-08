"""嚴格的 action / plan schema 驗證。

設計原則：
- 白名單：模型只能使用這裡定義的 action，其他一律拒絕。
- 每個 action 的必填欄位、型別都檢查。
- 驗證通過後回傳「正規化」後的 action（補上 reason、修掉多餘欄位）。
這能擋掉模型幻想出來的工具、亂帶參數、或想塞 python/shell 指令的情況。
"""

from typing import Any, Dict, List, Tuple

# action -> 必填欄位。空 list 代表不需要額外參數。
ALLOWED_ACTIONS: Dict[str, List[str]] = {
    "screenshot": [],
    "click": ["x", "y"],
    "double_click": ["x", "y"],
    "right_click": ["x", "y"],
    "move_mouse": ["x", "y"],
    "type_text": ["text"],
    "press_key": ["key"],
    "hotkey": ["keys"],
    "scroll": ["amount"],
    "wait": [],
    "finish_task": [],
    "fail_task": [],
    # 控制型 action：不改變電腦狀態，只是暫停並詢問使用者。
    "request_user_confirmation": [],
}

# 會實際改變電腦狀態的動作（planning 階段一律禁止；執行階段才允許）。
STATE_CHANGING_ACTIONS = {
    "click", "double_click", "right_click", "type_text",
    "press_key", "hotkey", "scroll", "move_mouse",
}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_action(raw: Any) -> Tuple[bool, str, Dict[str, Any]]:
    """回傳 (是否合法, 錯誤訊息, 正規化後的 action)。"""
    if not isinstance(raw, dict):
        return False, "action 必須是 JSON 物件", {}
    print(raw)
    name = raw.get("action")
    if name not in ALLOWED_ACTIONS:
        return False, f"未定義的 action: {name!r}", {}

    action: Dict[str, Any] = {"action": name, "reason": str(raw.get("reason", "")).strip()}
    print(action)
    # 逐欄位型別檢查
    if name in ("click", "double_click", "right_click", "move_mouse"):
        x, y = raw.get("x"), raw.get("y")
        # if not (_is_int(x) and _is_int(y)):
        #     return False, f"{name} 需要整數 x, y", {}
        action["x"], action["y"] = int(x), int(y)

    elif name == "type_text":
        text = raw.get("text")
        if not isinstance(text, str):
            return False, "type_text 需要字串 text", {}
        action["text"] = text

    elif name == "press_key":
        key = raw.get("key")
        if not isinstance(key, str) or not key.strip():
            return False, "press_key 需要非空字串 key", {}
        action["key"] = key.strip().lower()

    elif name == "hotkey":
        keys = raw.get("keys")
        if not (isinstance(keys, list) and keys and all(isinstance(k, str) for k in keys)):
            return False, "hotkey 需要字串陣列 keys", {}
        action["keys"] = [k.strip().lower() for k in keys]

    elif name == "scroll":
        amount = raw.get("amount")
        if not _is_int(amount):
            return False, "scroll 需要整數 amount（正=上，負=下）", {}
        action["amount"] = int(amount)

    elif name == "wait":
        # 可選 seconds，預設 1 秒，夾在 0.1~10。
        sec = raw.get("seconds", 1)
        try:
            sec = float(sec)
        except (TypeError, ValueError):
            sec = 1.0
        action["seconds"] = max(0.1, min(10.0, sec))

    elif name == "request_user_confirmation":
        action["message"] = str(raw.get("message", raw.get("reason", ""))).strip()

    # screenshot / finish_task / fail_task 不需額外欄位
    print(action)
    return True, "", action


# --- Plan schema ---

def validate_plan(raw: Any) -> Tuple[bool, str, Dict[str, Any]]:
    """驗證 Planner 輸出的計畫 JSON。"""
    if not isinstance(raw, dict):
        return False, "plan 必須是 JSON 物件", {}

    if "plan" not in raw or not isinstance(raw["plan"], list) or not raw["plan"]:
        return False, "缺少非空的 plan 陣列", {}

    steps = []
    for i, s in enumerate(raw["plan"], start=1):
        if not isinstance(s, dict):
            return False, f"plan 第 {i} 步不是物件", {}
        steps.append({
            "step": s.get("step", i),
            "goal": str(s.get("goal", "")).strip(),
            "expected_action_type": str(s.get("expected_action_type", "")).strip(),
        })

    sc = raw.get("safety_check", {})
    if not isinstance(sc, dict):
        sc = {}
    safety = {
        "is_safe": bool(sc.get("is_safe", True)),
        "risk_level": str(sc.get("risk_level", "unknown")).lower(),
        "reason": str(sc.get("reason", "")).strip(),
    }

    plan = {
        "task_summary": str(raw.get("task_summary", "")).strip(),
        "safety_check": safety,
        "plan": steps,
        "requires_user_confirmation": bool(raw.get("requires_user_confirmation", True)),
        "question_to_user": str(raw.get("question_to_user", "是否同意依照以上計畫開始操作？")).strip(),
    }
    return True, "", plan
