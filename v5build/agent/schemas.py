"""嚴格的 action / plan schema 驗證。

白名單設計：模型只能使用這裡定義的 action，其他一律拒絕。
Browser action（click_element / click_coordinate）和桌面 action（click / pyautogui）
共存，由 executor 決定怎麼執行。
"""

from typing import Any, Dict, List, Tuple

ALLOWED_ACTIONS: Dict[str, List[str]] = {
    # --- Browser 層（透過 WebSocket bridge）---
    "click_element":   ["element_id"],
    "click_coordinate": ["x", "y"],
    # --- 通用（browser 與桌面共用）---
    "type_text":       ["text"],
    "press_key":       ["key"],
    "hotkey":          ["keys"],
    "scroll":          ["amount"],
    "wait":            [],
    "screenshot":      [],
    "finish_task":     [],
    "fail_task":       [],
    "request_user_confirmation": [],
    # --- 桌面 fallback（pyautogui）---
    "click":           ["x", "y"],
    "double_click":    ["x", "y"],
    "right_click":     ["x", "y"],
    "move_mouse":      ["x", "y"],
}

STATE_CHANGING_ACTIONS = {
    "click_element", "click_coordinate",
    "click", "double_click", "right_click", "move_mouse",
    "type_text", "press_key", "hotkey", "scroll",
}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_action(raw: Any) -> Tuple[bool, str, Dict[str, Any]]:
    """回傳 (是否合法, 錯誤訊息, 正規化後的 action)。"""
    if not isinstance(raw, dict):
        return False, "action 必須是 JSON 物件", {}

    name = raw.get("action")
    if name not in ALLOWED_ACTIONS:
        return False, f"未定義的 action: {name!r}", {}

    action: Dict[str, Any] = {"action": name, "reason": str(raw.get("reason", "")).strip(), "observation": str(raw.get("observation", "")).strip(), "plan": str(raw.get("plan", "")).strip()}

    if name == "click_element":
        eid = raw.get("element_id")
        if not isinstance(eid, str) or not eid.strip():
            return False, "click_element 需要非空字串 element_id", {}
        action["element_id"] = eid.strip()

    elif name == "click_coordinate":
        x, y = raw.get("x"), raw.get("y")
        if not (_is_int(x) and _is_int(y)):
            return False, "click_coordinate 需要整數 x, y", {}
        action["x"], action["y"] = int(x), int(y)

    elif name in ("click", "double_click", "right_click", "move_mouse"):
        x, y = raw.get("x"), raw.get("y")
        if not (_is_int(x) and _is_int(y)):
            return False, f"{name} 需要整數 x, y", {}
        action["x"], action["y"] = int(x), int(y)

    elif name == "type_text":
        text = raw.get("text")
        if not isinstance(text, str):
            return False, "type_text 需要字串 text", {}
        action["text"] = text
        eid = raw.get("element_id")
        if isinstance(eid, str) and eid.strip():
            action["element_id"] = eid.strip()

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
        sec = raw.get("seconds", 1)
        try:
            sec = float(sec)
        except (TypeError, ValueError):
            sec = 1.0
        action["seconds"] = max(0.1, min(10.0, sec))

    elif name == "request_user_confirmation":
        action["message"] = str(raw.get("message", raw.get("reason", ""))).strip()

    return True, "", action


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
    safety_obj = {
        "is_safe": bool(sc.get("is_safe", True)),
        "risk_level": str(sc.get("risk_level", "unknown")).lower(),
        "reason": str(sc.get("reason", "")).strip(),
    }
    plan = {
        "task_summary": str(raw.get("task_summary", "")).strip(),
        "safety_check": safety_obj,
        "plan": steps,
        "requires_user_confirmation": bool(raw.get("requires_user_confirmation", True)),
        "question_to_user": str(raw.get("question_to_user", "是否同意依照以上計畫開始操作？")).strip(),
    }
    return True, "", plan
