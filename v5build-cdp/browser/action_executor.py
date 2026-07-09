"""Browser Action Executor

透過 WebSocket bridge 在 Extension/瀏覽器端執行 action。
設計成可替換：executor 決定怎麼執行（JS DOM / CDP / pyautogui），
agent loop 只依賴通用的 action schema，不綁死任何執行方式。

支援的 action（瀏覽器層）：
    click_element       — 由 Extension JS 找到 element_id 對應元素執行 .click()
    select_element      — 選擇下拉選單中的選項
    type_text           — 在目前 focus 元素輸入文字（或傳 element_id 先 focus）
    press_key           — 送 KeyboardEvent
    hotkey              — 送組合鍵 KeyboardEvent
    scroll              — 捲動頁面
    wait                — 等待指定秒數（Python 端執行，不需橋接）
    finish_task         — loop 終止訊號，不由 executor 執行
    fail_task           — loop 終止訊號，不由 executor 執行

後續要改成真實滑鼠鍵盤：只需在 _dispatch_browser_action 加判斷，
或建立 DesktopActionExecutor，agent loop 不需要改。
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from agent.logger import RunLogger
from browser.observation_provider import BrowserBridgeManager

logger = logging.getLogger(__name__)

# action 名稱常數，避免 magic string
ACTION_CLICK_ELEMENT = "click_element"
ACTION_CLICK_COORDINATE = "click_coordinate"
ACTION_SELECT_ELEMENT = "select_element"
ACTION_TYPE_TEXT = "type_text"
ACTION_PRESS_KEY = "press_key"
ACTION_HOTKEY = "hotkey"
ACTION_SCROLL = "scroll"
ACTION_WAIT = "wait"
ACTION_FINISH_TASK = "finish_task"
ACTION_FAIL_TASK = "fail_task"
ACTION_REQUEST_CONFIRM = "request_user_confirmation"

# 不需要橋接到 Extension，直接在 Python 端處理的 action
_PYTHON_SIDE_ACTIONS = {ACTION_WAIT, ACTION_FINISH_TASK, ACTION_FAIL_TASK, ACTION_REQUEST_CONFIRM}


class BrowserActionExecutor:
    """透過 BrowserBridgeManager 在瀏覽器端執行 action。

    若 bridge 未連線，回傳 ok=False 並附上錯誤訊息，不拋例外。
    """

    def __init__(self, bridge: BrowserBridgeManager, logger: RunLogger, action_delay: float = 0.4):
        self.bridge = bridge
        self.logger = logger
        self.action_delay = action_delay

    async def execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """執行單一 action，回傳 {ok, ...}。"""
        name = action.get("action", "")
        t_start = time.time()

        try:
            result = await self._dispatch(name, action)
        except Exception as exc:
            logger.error("[BrowserExecutor] action=%s 執行失敗: %s", name, exc)
            result = {"ok": False, "error": str(exc)}

        elapsed_ms = int((time.time() - t_start) * 1000)
        result["elapsed_ms"] = elapsed_ms
        logger.info(
            "[BrowserExecutor] action=%s ok=%s elapsed=%dms",
            name, result.get("ok"), elapsed_ms,
        )

        # 執行後稍作等待，讓頁面有時間反應
        if name not in _PYTHON_SIDE_ACTIONS:
            await asyncio.sleep(self.action_delay)

        return result

    async def _dispatch(self, name: str, action: Dict[str, Any]) -> Dict[str, Any]:
        # --- Python 端處理 ---
        if name == ACTION_WAIT:
            seconds = float(action.get("seconds", 1.0))
            await asyncio.sleep(max(0.1, min(10.0, seconds)))
            return {"ok": True, "waited_sec": seconds}

        if name in (ACTION_FINISH_TASK, ACTION_FAIL_TASK, ACTION_REQUEST_CONFIRM):
            # loop 層處理，executor 直接回 ok=True 讓 loop 繼續判斷
            return {"ok": True, "noop": name}

        # --- 橋接到 Extension 執行 ---
        if not self.bridge.is_connected:
            return {"ok": False, "error": "Extension WebSocket 尚未連線"}

        return await self._dispatch_browser_action(name, action)

    async def _dispatch_browser_action(
        self, name: str, action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """將 action 送到 Extension 執行，回傳 result。"""
        params: Dict[str, Any] = {}

        if name == ACTION_CLICK_ELEMENT:
            self.logger.log(f"{ACTION_CLICK_ELEMENT}", action = action['element_id'])
            params = {"element_id": action["element_id"]}

        elif name == ACTION_CLICK_COORDINATE:
            self.logger.log(f"{ACTION_CLICK_COORDINATE}", x = action['x'], y = action['y'])
            params = {"x": action["x"], "y": action["y"]}

        elif name == ACTION_SELECT_ELEMENT:
            self.logger.log(f"{ACTION_SELECT_ELEMENT}", element_id = action['element_id'], value = action['value'])
            params = {"element_id": action["element_id"], "value": action["value"]}

        elif name == ACTION_TYPE_TEXT:
            self.logger.log(f"{ACTION_TYPE_TEXT}", text = action['text'])
            params = {
                "text": action["text"],
                "element_id": action.get("element_id"),   # 可選，有的話先 focus
            }

        elif name == ACTION_PRESS_KEY:
            self.logger.log(f"{ACTION_PRESS_KEY}", key = action['key'])
            params = {"key": action["key"]}

        elif name == ACTION_HOTKEY:
            self.logger.log(f"{ACTION_HOTKEY}", keys = action['keys'])
            params = {"keys": action["keys"]}

        elif name == ACTION_SCROLL:
            self.logger.log(f"{ACTION_SCROLL}", amount = action['amount'])
            params = {"amount": action["amount"]}

        else:
            self.logger.log("[BrowserExecutor] 不支援的 action: %s", name)
            return {"ok": False, "error": f"BrowserActionExecutor 不支援 action={name}"}

        try:
            result = await self.bridge.send_command(name, params)
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
