"""螢幕截圖、縮放、座標換算、畫面雜湊。

重要觀念（座標換算）：
- 我們把整張螢幕截圖，等比例縮到寬度 <= MODEL_MAX_WIDTH 再送給模型。
- 模型（qwen2.5vl）會依「牠實際看到的那張圖」的像素座標回報位置。
- 因此模型給的 (x, y) 是在「縮圖座標系」，程式要用縮放比例換回「真實螢幕座標」。
- 若點擊位置有系統性偏移，多半是這個換算或多螢幕 offset 造成，看 debug 截圖即可校正。
"""

import base64
import io
import os
import time
from typing import Dict, Tuple

import mss
from PIL import Image


def scale_dimensions(w: int, h: int, max_width: int) -> Tuple[int, int, float]:
    """回傳 (縮圖寬, 縮圖高, scale)。scale = 縮圖 / 原圖。"""
    if w <= max_width:
        return w, h, 1.0
    scale = max_width / float(w)
    return max_width, int(round(h * scale)), scale


def model_to_real(x: int, y: int, scale: float, offset: Tuple[int, int]) -> Tuple[int, int]:
    """把模型（縮圖座標系）的座標換回真實螢幕座標。"""
    ox, oy = offset
    return int(round(x / scale)) + ox, int(round(y / scale)) + oy


class ScreenManager:
    def __init__(self, monitor_index: int, model_max_width: int, screenshot_dir: str):
        self.monitor_index = monitor_index
        self.model_max_width = model_max_width
        self.screenshot_dir = screenshot_dir
        os.makedirs(screenshot_dir, exist_ok=True)
        with mss.mss() as sct:
            mons = sct.monitors
            idx = monitor_index if monitor_index < len(mons) else 1
            mon = mons[idx]
            # 目標螢幕在整個虛擬桌面中的左上角 offset（多螢幕時 pyautogui 需要）。
            self.offset = (mon["left"], mon["top"])
            self.real_size = (mon["width"], mon["height"])
        self._last_scale = 1.0

    def capture(self, tag: str = "step") -> Dict:
        """截圖 -> 存 debug 檔 -> 回傳 dict：
        {image_b64, path, real_size, model_size, scale, phash}
        """
        with mss.mss() as sct:
            mon = sct.monitors[self.monitor_index if self.monitor_index < len(sct.monitors) else 1]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        real_w, real_h = img.size
        mw, mh, scale = scale_dimensions(real_w, real_h, self.model_max_width)
        self._last_scale = scale
        small = img.resize((mw, mh)) if scale != 1.0 else img

        # 存 debug 截圖（存縮圖，代表模型真正看到的畫面）
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.screenshot_dir, f"{ts}_{tag}.png")
        small.save(path)

        buf = io.BytesIO()
        small.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "image_b64": image_b64,
            "path": path,
            "real_size": (real_w, real_h),
            "model_size": (mw, mh),
            "scale": scale,
            "phash": self._phash(small),
        }

    def to_real_coords(self, x: int, y: int, scale: float) -> Tuple[int, int]:
        return model_to_real(x, y, scale, self.offset)

    @staticmethod
    def _phash(img: Image.Image) -> str:
        """非常簡單的 average hash，用來判斷畫面是否有變化。"""
        g = img.convert("L").resize((16, 16))
        pixels = list(g.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p >= avg else "0" for p in pixels)
        return f"{int(bits, 2):064x}"
