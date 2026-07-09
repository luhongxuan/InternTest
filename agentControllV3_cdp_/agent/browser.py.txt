"""CDP 瀏覽器層（不使用 Playwright）。

連到用 remote debugging port 啟動的 Edge/Chrome，提供：
- capture()      ：Page.captureScreenshot（截圖）+ 注入 JS 抓可互動元素（元素清單）
- click_element():Input.dispatchMouseEvent 點元素中心（CDP 點擊）
- type_in_element()：點元素 + Input.insertText
- get_url_title()

啟動瀏覽器（Windows / Edge）：
    msedge.exe --remote-debugging-port=9222 --user-data-dir=C:\\edge-cdp
（Chrome 換成 chrome.exe 即可）

座標說明：元素 bounds 與 Input 事件都用「視窗 CSS 座標」，兩者一致，不需 DPR 換算。
送給模型的截圖會縮到 MODEL_MAX_WIDTH（只是視覺參考，模型是用文字清單挑 #id）。
"""

import base64
import io
import json
from typing import Any, Dict, List, Optional, Tuple

import requests
import websocket  # pip install websocket-client
from PIL import Image

# 抓可互動元素的注入腳本：回傳每個可見元素的 tag/role/name/中心座標。
_ELEMENTS_JS = r"""
(() => {
  const q = 'a,button,input,textarea,select,[role=button],[role=link],[role=tab],[role=menuitem],[onclick],[contenteditable="true"]';
  const out = [];
  document.querySelectorAll(q).forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') return;
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || el.type || '',
      name: (el.innerText || el.value || el.placeholder ||
             el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 80),
      cx: Math.round(r.left + r.width / 2),
      cy: Math.round(r.top + r.height / 2)
    });
  });
  return out;
})()
"""


class BrowserCDP:
    def __init__(self, host: str = "127.0.0.1", port: int = 9222,
                 model_max_width: int = 1028, timeout: int = 20):
        self.base = f"http://{host}:{port}"
        self.model_max_width = model_max_width
        self.timeout = timeout
        self._id = 0
        self.ws = self._connect()

    def _connect(self) -> "websocket.WebSocket":
        # 取得目前分頁 target 的 websocket url
        targets = requests.get(f"{self.base}/json", timeout=self.timeout).json()
        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if not pages:
            raise RuntimeError("找不到可用的瀏覽器分頁，請確認 Edge 以 --remote-debugging-port 啟動")
        ws_url = pages[0]["webSocketDebuggerUrl"]
        ws = websocket.create_connection(ws_url, max_size=None, timeout=self.timeout)
        return ws

    def _send(self, method: str, params: Optional[Dict] = None) -> Dict:
        """送一個 CDP 命令並等對應 id 的回覆（跳過事件訊息）。"""
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            data = json.loads(self.ws.recv())
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP {method} 失敗：{data['error']}")
                return data.get("result", {})
            # 其餘為事件，忽略

    # ---------- 觀察 ----------
    def capture(self) -> Dict[str, Any]:
        """回傳 {image_base64, elements, model_size, scale}。元素座標為 CSS px。"""
        self._send("Page.bringToFront")
        shot = self._send("Page.captureScreenshot", {"format": "png"})
        raw_b64 = shot["data"]

        # 縮圖給模型（只是視覺參考）
        img = Image.open(io.BytesIO(base64.b64decode(raw_b64))).convert("RGB")
        w, h = img.size
        if w > self.model_max_width:
            scale = self.model_max_width / float(w)
            img = img.resize((self.model_max_width, int(round(h * scale))))
        else:
            scale = 1.0
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        res = self._send("Runtime.evaluate", {"expression": _ELEMENTS_JS, "returnByValue": True})
        elements: List[Dict] = res.get("result", {}).get("value", []) or []

        return {
            "image_base64": image_base64,
            "elements": elements,
            "model_size": img.size,
            "scale": scale,
        }

    def get_url_title(self) -> Tuple[str, str]:
        r = self._send("Runtime.evaluate",
                       {"expression": "[location.href, document.title]", "returnByValue": True})
        v = r.get("result", {}).get("value", ["", ""])
        return v[0], v[1]

    # ---------- 操作（CDP 點擊） ----------
    def _click_xy(self, x: int, y: int) -> None:
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            self._send("Input.dispatchMouseEvent", {
                "type": t, "x": x, "y": y,
                "button": "left", "buttons": 1, "clickCount": 1,
            })

    def click_element(self, elements: List[Dict], element_id: int) -> Dict[str, Any]:
        if not (0 <= element_id < len(elements)):
            return {"ok": False, "error": f"element_id {element_id} 超出範圍"}
        el = elements[element_id]
        self._click_xy(el["cx"], el["cy"])
        return {"ok": True, "clicked": el.get("name", ""), "xy": (el["cx"], el["cy"])}

    def type_in_element(self, elements: List[Dict], element_id: int, text: str) -> Dict[str, Any]:
        if not (0 <= element_id < len(elements)):
            return {"ok": False, "error": f"element_id {element_id} 超出範圍"}
        el = elements[element_id]
        self._click_xy(el["cx"], el["cy"])          # 先聚焦
        self._send("Input.insertText", {"text": text})
        return {"ok": True, "typed_len": len(text)}

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
