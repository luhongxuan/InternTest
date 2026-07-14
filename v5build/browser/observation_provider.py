"""Browser Observation Provider

負責透過 WebSocket bridge 向 Extension 取得頁面觀察資料。

BrowserBridgeManager  — 管理 WebSocket 連線、收發命令。
BrowserObservationProvider — 發出 get_page_observation 命令，
                             將 Extension 回傳的原始資料正規化成
                             統一的 BrowserObservation schema。

設計原則：
- Python 後端不直接依賴 JS 內部 DOM 實作，只依賴統一的 observation schema。
- 每個命令都有 command_id，response 以 command_id 對應，避免混包。
- timeout 可設定；連線中斷時回傳明確的錯誤資訊，不讓 agent loop crash。
"""

import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import WebSocket
from PIL import Image

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema: 對外統一輸出的 BrowserObservation
# ---------------------------------------------------------------------------

@dataclass
class ElementBounds:
    x: float
    y: float
    width: float
    height: float


@dataclass
class InteractiveElement:
    element_id: str
    tag: str
    role: str
    text: str
    label: str
    aria_label: str
    placeholder: str
    title: str
    bounds: ElementBounds
    visible: bool
    enabled: bool
    clickable: bool
    inputtable: bool
    nearby_text: str
    occluded: bool = False          # 第一版由 elementFromPoint 判斷，可後續補強


@dataclass
class BrowserObservation:
    environment: str                 # "browser"
    page_url: str
    page_title: str
    viewport_width: int
    viewport_height: int
    device_scale_factor: float
    screenshot_path: str
    screenshot_base64: str           # 縮圖供模型使用
    screenshot_width: int
    screenshot_height: int
    elements: List[InteractiveElement]
    raw_elements_count: int          # 原始 DOM 找到的元素數（含不可見）
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None      # 若 bridge 回報錯誤


def _parse_observation(raw: Dict[str, Any], screenshot_dir: str) -> BrowserObservation:
    """將 Extension 回傳的原始 JSON 正規化成 BrowserObservation。"""
    page = raw.get("page", {})
    viewport = raw.get("viewport", {})
    elements_raw: List[Dict] = raw.get("elements", [])

    # --- 儲存截圖 ---
    screenshot_b64_original: str = raw.get("screenshot_base64", "")
    screenshot_path = ""
    screenshot_b64_model = ""
    screenshot_width = viewport.get("width", 0)
    screenshot_height = viewport.get("height", 0)

    if screenshot_b64_original:
        try:
            img = Image.open(io.BytesIO(base64.b64decode(screenshot_b64_original))).convert("RGB")
            # 縮圖供模型
            if img.width > config.MODEL_MAX_WIDTH:
                scale = config.MODEL_MAX_WIDTH / float(img.width)
                img_model = img.resize(
                    (config.MODEL_MAX_WIDTH, int(round(img.height * scale)))
                )
            else:
                img_model = img
            screenshot_width, screenshot_height = img_model.size
            # 儲存 debug 截圖
            os.makedirs(screenshot_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(screenshot_dir, f"browser_{ts}.png")
            #img_model.save(screenshot_path)
            # base64 供模型
            buf = io.BytesIO()
            img_model.save(buf, format="PNG")
            screenshot_b64_model = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as exc:
            logger.warning("截圖處理失敗: %s", exc)

    # --- 正規化元素 ---
    elements: List[InteractiveElement] = []
    for el in elements_raw:
        bounds_raw = el.get("bounds", {})
        bounds = ElementBounds(
            x=float(bounds_raw.get("x", 0)),
            y=float(bounds_raw.get("y", 0)),
            width=float(bounds_raw.get("width", 0)),
            height=float(bounds_raw.get("height", 0)),
        )
        elements.append(InteractiveElement(
            element_id=str(el.get("element_id", "")),
            tag=str(el.get("tag", "")),
            role=str(el.get("role", "")),
            text=str(el.get("text", ""))[:120],
            label=str(el.get("label", "")),
            aria_label=str(el.get("aria_label", "")),
            placeholder=str(el.get("placeholder", "")),
            title=str(el.get("title", "")),
            bounds=bounds,
            visible=bool(el.get("visible", True)),
            enabled=bool(el.get("enabled", True)),
            clickable=bool(el.get("clickable", False)),
            inputtable=bool(el.get("inputtable", False)),
            nearby_text=str(el.get("nearby_text", ""))[:80],
            occluded=bool(el.get("occluded", False)),
        ))
    
    return BrowserObservation(
        environment="browser",
        page_url=str(page.get("url", "")),
        page_title=str(page.get("title", "")),
        viewport_width=int(viewport.get("width", 0)),
        viewport_height=int(viewport.get("height", 0)),
        device_scale_factor=float(viewport.get("device_scale_factor", 1.0)),
        screenshot_path=screenshot_path,
        screenshot_base64=screenshot_b64_model,
        screenshot_width=screenshot_width,
        screenshot_height=screenshot_height,
        elements=elements,
        raw_elements_count=int(raw.get("raw_elements_count", len(elements_raw))),
    )


# ---------------------------------------------------------------------------
# BrowserBridgeManager — WebSocket 連線管理與命令收發
# ---------------------------------------------------------------------------

class BrowserBridgeManager:
    """管理來自 Extension 的 WebSocket 連線。

    同一時間只允許一條連線（Extension 只會開一個 side panel）。
    命令以 command_id (UUID) 對應回覆，避免非同步混包。
    """

    def __init__(self):
        self._websocket: Optional[WebSocket] = None
        self._pending: Dict[str, asyncio.Future] = {}   # command_id → Future
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._websocket is not None

    async def accept(self, websocket: WebSocket) -> None:
        """由 FastAPI WebSocket route 呼叫，接受 Extension 連線。"""
        await websocket.accept()
        async with self._lock:
            self._websocket = websocket
            self._connected = True
        logger.info("[Bridge] Extension 已連線")
        try:
            await self._receive_loop()
        finally:
            async with self._lock:
                self._connected = False
                self._websocket = None
            # 讓所有等待中的 Future 失敗，避免 agent loop 永久阻塞
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Extension WebSocket 連線中斷"))
            self._pending.clear()
            logger.info("[Bridge] Extension 連線中斷")

    async def _receive_loop(self) -> None:
        """持續接收來自 Extension 的訊息，將回覆分發給對應的 Future。"""
        ws = self._websocket
        while True:
            try:
                text = await ws.receive_text()
            except Exception:
                break
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("[Bridge] 收到非 JSON 訊息: %s", text[:200])
                continue
            command_id = msg.get("command_id")
            if command_id and command_id in self._pending:
                fut = self._pending.pop(command_id)
                if not fut.done():
                    if msg.get("error"):
                        fut.set_exception(RuntimeError(msg["error"]))
                    else:
                        fut.set_result(msg.get("result", {}))
            else:
                logger.debug("[Bridge] 收到未對應訊息 command_id=%s", command_id)

    async def send_command(
        self,
        command_type: str,
        params: Optional[Dict[str, Any]] = None,
        timeout_sec: float = config.WS_COMMAND_TIMEOUT_SEC,
    ) -> Dict[str, Any]:
        """送出命令並等待 Extension 回傳 result。

        回傳 result dict；若連線不存在或逾時則拋出例外。
        """
        if not self.is_connected or self._websocket is None:
            raise ConnectionError("Extension WebSocket 尚未連線，請先開啟 Extension 側邊欄")

        command_id = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[command_id] = fut

        payload = json.dumps({
            "command_id": command_id,
            "command_type": command_type,
            "params": params or {},
        })
        t_send = time.time()
        try:
            await self._websocket.send_text(payload)
            result = await asyncio.wait_for(fut, timeout=timeout_sec)
        except asyncio.TimeoutError:
            self._pending.pop(command_id, None)
            raise TimeoutError(
                f"[Bridge] command={command_type} command_id={command_id} "
                f"逾時 {timeout_sec}s"
            )
        except Exception:
            self._pending.pop(command_id, None)
            raise

        elapsed_ms = int((time.time() - t_send) * 1000)
        logger.debug(
            "[Bridge] command=%s command_id=%s elapsed=%dms",
            command_type, command_id, elapsed_ms,
        )
        return result


# ---------------------------------------------------------------------------
# BrowserObservationProvider — 高層封裝，取得 BrowserObservation
# ---------------------------------------------------------------------------

class BrowserObservationProvider:
    """發出 get_page_observation 命令，取得並正規化頁面觀察資料。"""

    def __init__(self, bridge: BrowserBridgeManager, screenshot_dir: str = config.SCREENSHOT_DIR):
        self.bridge = bridge
        self.screenshot_dir = screenshot_dir

    async def get_observation(self) -> BrowserObservation:
        """取得目前頁面的完整觀察資料（元素 + 截圖）。

        若 bridge 未連線或發生錯誤，回傳含有 error 欄位的 BrowserObservation，
        不拋例外，讓 agent loop 自行決定如何處理。
        """
        if not self.bridge.is_connected:
            return BrowserObservation(
                environment="browser",
                page_url="", page_title="",
                viewport_width=0, viewport_height=0, device_scale_factor=1.0,
                screenshot_path="", screenshot_base64="",
                screenshot_width=0, screenshot_height=0,
                elements=[], raw_elements_count=0,
                error="Extension WebSocket 尚未連線",
            )
        try:
            raw = await self.bridge.send_command("get_page_observation")
            obs = _parse_observation(raw, self.screenshot_dir)
            logger.info(
                "[Observation] url=%s elements=%d screenshot=%s",
                obs.page_url, len(obs.elements), obs.screenshot_path,
            )
            return obs
        except Exception as exc:
            logger.error("[Observation] 取得觀察資料失敗: %s", exc)
            return BrowserObservation(
                environment="browser",
                page_url="", page_title="",
                viewport_width=0, viewport_height=0, device_scale_factor=1.0,
                screenshot_path="", screenshot_base64="",
                screenshot_width=0, screenshot_height=0,
                elements=[], raw_elements_count=0,
                error=str(exc),
            )


def format_elements_for_prompt(elements: List[InteractiveElement]) -> str:
    """將元素清單格式化成模型好讀的文字（一行一個）。"""
    if not elements:
        return "(目前頁面無可互動元素)"
    lines: List[str] = []
    filtered = [
        e for e in elements
        if e.tag in ("select", "input", "textarea", "button")
        or (e.tag == "a" and (e.aria_label or e.title or e.placeholder))
    ]
    if not filtered:
        filtered = elements
    elements = sorted(filtered, key=lambda e: (e.bounds.y, e.bounds.x))
    print(len(elements), "elements after filter and sort")
    for el in elements:
        role_or_tag = el.role or el.tag
        purpose = (el.title or el.nearby_text or el.aria_label or el.label or el.placeholder or "").strip()
        display_name = (el.text or "").replace("\n", "/").strip()[:30]
        b = el.bounds
        flags = []
        if el.clickable:
            flags.append("可點擊")
        if el.inputtable:
            flags.append("可輸入")
        if el.occluded:
            flags.append("⚠被遮擋")
        flag_str = " ".join(flags)
        lines.append(
            f"{el.element_id} | {el.tag:8s} | 用途:{purpose:15s} | 內容:{display_name}"
            f'@({int(b.x)},{int(b.y)}) {int(b.width)}x{int(b.height)} | {flag_str}'
        )
    return "\n".join(lines)
