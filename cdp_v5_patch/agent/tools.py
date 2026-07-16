"""通用工具執行器：把驗證過的 action 轉成實際的滑鼠鍵盤操作。

只提供通用工具，完全不含任何特定軟體流程。
- 座標一律夾在螢幕範圍內，避免 pyautogui 因越界或 FAILSAFE 直接丟例外。
- type_text 用剪貼簿貼上，才能正確輸入中文與特殊字元。
- 危險系統操作不在這裡；那些在 safety.py 就被擋掉或要求確認。
"""

import time
from typing import Any, Dict, Tuple

import pyautogui
import pyperclip

# 滑鼠移到左上角可緊急中止（pyautogui 內建 failsafe）。
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3  # 我們自己控制延遲


class ToolExecutor:
    def __init__(self, screen_manager, action_delay: float):
        self.screen = screen_manager
        self.action_delay = action_delay
        self.real_w, self.real_h = screen_manager.real_size
        self.offset = screen_manager.offset

    def _clamp(self, x: int, y: int) -> Tuple[int, int]:
        ox, oy = self.offset
        cx = min(max(x, ox), ox + self.real_w - 1)
        cy = min(max(y, oy), oy + self.real_h - 1)
        return cx, cy

    def execute(self, action: Dict[str, Any], scale: float) -> Dict[str, Any]:
        """執行單一 action，回傳結果 dict。不會拋例外（都轉成 ok=False）。"""
        name = action["action"]
        try:
            result = self._dispatch(name, action, scale)
            time.sleep(self.action_delay)
            return {"ok": True, **result}
        except pyautogui.FailSafeException:
            return {"ok": False, "error": "使用者觸發 FAILSAFE（滑鼠移到角落），已中止"}
        except Exception as e:  # noqa: BLE001 - 工具層要吞掉例外，交由迴圈判斷
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _dispatch(self, name: str, action: Dict[str, Any], scale: float) -> Dict[str, Any]:
        if name in ("click", "double_click", "right_click", "move_mouse"):
            rx, ry = self.screen.to_real_coords(action["x"], action["y"], scale)
            rx, ry = self._clamp(rx, ry)
            pyautogui.moveTo(rx, ry, duration=0.1)
            if name == "click":
                pyautogui.click(rx, ry)
            elif name == "double_click":
                pyautogui.doubleClick(rx, ry)
            elif name == "right_click":
                pyautogui.rightClick(rx, ry)
            return {"real_coords": (rx, ry)}

        if name == "type_text":
            text = action["text"]
            try:
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
            except Exception:
                pyautogui.typewrite(text, interval=0.02)  # ASCII fallback
            return {"typed_len": len(text)}

        if name == "press_key":
            pyautogui.press(action["key"])
            return {"key": action["key"]}

        if name == "hotkey":
            pyautogui.hotkey(*action["keys"])
            return {"keys": action["keys"]}

        if name == "scroll":
            pyautogui.scroll(action["amount"] * 100)
            return {"amount": action["amount"]}

        if name == "wait":
            time.sleep(action.get("seconds", 1))
            return {"waited": action.get("seconds", 1)}

        # screenshot / finish_task / fail_task / request_user_confirmation
        # 這些不在此處產生實際 OS 操作，由 agent_loop 處理。
        return {"noop": name}
