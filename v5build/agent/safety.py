"""基本安全機制。

分成三類：
1. 任務/計畫層級：關鍵字掃描，偵測危險任務。
2. 單一 action 層級：危險 hotkey 阻擋、需要確認的動作標記。
3. 迴圈層級：重複動作、畫面無變化的偵測。

注意：這是「務實的第一層防護」，不是完整資安沙箱。真正高風險的操作
（下單、付款、刪檔）仍應靠人為 approve 與模型自我克制，不能只靠關鍵字。
"""

from typing import Any, Dict, List, Optional, Tuple

# 危險任務關鍵字（中英）。命中就把 risk 拉高、要求更明確確認。
DANGER_KEYWORDS = [
    "刪除", "delete", "格式化", "format", "下單", "買進", "賣出", "委託",
    "交易", "trade", "付款", "轉帳", "匯款", "pay", "purchase", "checkout",
    "密碼", "password", "登入", "credential", "私鑰", "private key",
    "解除安裝", "uninstall", "登錄檔", "registry", "shutdown", "關機",
    "rm -rf", "powershell", "cmd", "shell", "系統設定",
]

# 直接封鎖的危險 hotkey 組合（開啟執行框/終端機/系統操作）。
BLOCKED_HOTKEYS = [
    frozenset({"win", "r"}),          # 執行對話框
    frozenset({"ctrl", "shift", "esc"}),  # 工作管理員
    frozenset({"ctrl", "alt", "delete"}),
]

# 需要使用者二次確認、但不直接封鎖的 hotkey。
CONFIRM_HOTKEYS = [
    frozenset({"alt", "f4"}),         # 關閉視窗
    frozenset({"ctrl", "w"}),         # 關閉分頁/視窗
]


def scan_task_risk(task: str, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """掃描任務文字與計畫，回傳風險評估。"""
    haystack = task.lower()
    if plan:
        haystack += " " + str(plan).lower()
    hits = [kw for kw in DANGER_KEYWORDS if kw.lower() in haystack]
    if hits:
        return {"is_safe": False, "risk_level": "high",
                "reason": f"偵測到高風險關鍵字：{', '.join(sorted(set(hits)))}", "hits": hits}
    return {"is_safe": True, "risk_level": "low", "reason": "未偵測到明顯高風險關鍵字", "hits": []}


def check_action_safety(action: Dict[str, Any]) -> Tuple[str, str]:
    """檢查單一 action。回傳 (verdict, reason)。
    verdict ∈ {"allow", "confirm", "block"}。
    """
    name = action.get("action")

    if name == "hotkey":
        combo = frozenset(action.get("keys", []))
        if combo in BLOCKED_HOTKEYS:
            return "block", f"封鎖危險快捷鍵：{'+'.join(action.get('keys', []))}"
        if combo in CONFIRM_HOTKEYS:
            return "confirm", f"此快捷鍵可能關閉視窗，需確認：{'+'.join(action.get('keys', []))}"

    if name == "type_text":
        text = action.get("text", "")
        low = text.lower()
        if any(kw in low for kw in ["rm -rf", "powershell", "format ", "del /"]):
            return "block", "輸入內容疑似系統/破壞性指令"

    # 模型主動要求確認
    if name == "request_user_confirmation":
        return "confirm", action.get("message") or "模型要求使用者確認"

    return "allow", ""


class LoopGuard:
    """偵測重複動作與畫面無變化。"""

    def __init__(self, max_repeat: int, max_no_change: int):
        self.max_repeat = max_repeat
        self.max_no_change = max_no_change
        self._last_sig: Optional[str] = None
        self._repeat_count = 0
        self._last_screen_hash: Optional[str] = None
        self._no_change_count = 0

    @staticmethod
    def _action_signature(action: Dict[str, Any]) -> str:
        keys = ("action", "x", "y", "text", "key", "keys", "amount")
        return "|".join(f"{k}={action.get(k)}" for k in keys)

    def record_action(self, action: Dict[str, Any]) -> Optional[str]:
        """回傳 None 代表正常；回傳字串代表應中止的原因。"""
        sig = self._action_signature(action)
        if sig == self._last_sig:
            self._repeat_count += 1
        else:
            self._repeat_count = 1
            self._last_sig = sig
        # if self._repeat_count >= self.max_repeat:
        #     return f"同一動作連續重複 {self._repeat_count} 次，中止避免卡死"
        return None

    def record_screen(self, screen_hash: str) -> Optional[str]:
        if screen_hash == self._last_screen_hash:
            self._no_change_count += 1
        else:
            self._no_change_count = 0
            self._last_screen_hash = screen_hash
        if self._no_change_count >= self.max_no_change:
            return f"畫面連續 {self._no_change_count} 次未變化，中止避免無效迴圈"
        return None
