"""
螢幕截圖
"""

import base64
import io
import os
import time

import mss
from PIL import Image

class ScreenManager:
    def __init__(self, model_max_width: int = 1280, screenshot_dir: str = "screenshots"):
        self.sct = mss.MSS()
        if len(self.sct.monitors) > 2:
            self.monitor = self.sct.monitors[1]
        else:
            self.monitor = self.sct.monitors[1]
        self.model_max_width = model_max_width
        self.screenshot_dir = screenshot_dir
        self.offset = (self.monitor["left"], self.monitor["top"])
        self.real_size = (self.monitor["width"], self.monitor["height"])
        self.last_scale = 1.0

        self.buffer = io.BytesIO()

    def scale_dimensions(self, width: int, height: int, max_width: int):
        if width < max_width:
            return width, height, 1.0
        scale = max_width / float(width)
        return int(round(width * scale)), int(round(height * scale)), scale

    def capture_screen(self):
        sct_image = self.sct.grab(self.monitor)
        sct_image = Image.frombytes("RGB", sct_image.size, sct_image.bgra, "raw", "BGRX")

        scale_width, scale_height, scale = self.scale_dimensions(
            sct_image.width, sct_image.height, self.model_max_width
        )
        self.last_scale = scale
        scale_image = sct_image.resize((scale_width, scale_height)) if scale < 1.0 else sct_image   

        #ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.screenshot_dir, f"screenshot.png")
        scale_image.save(path)

        self.buffer.seek(0)
        self.buffer.truncate(0)

        scale_image.save(self.buffer, format="PNG")
        image_base64 = base64.b64encode(self.buffer.getvalue()).decode("utf-8")

        return {
            "image_base64": image_base64,
            "path": path,
            "scale": scale,
            "model_size": (scale_width, scale_height),
            "phash": self._phash(scale_image)
        }
    
    def to_real_coordinates(self, x: int, y: int, scale) -> tuple[int, int]:
        return int(round(x / scale)) + self.offset[0], int(round(y / scale)) + self.offset[1]   
    
    def _phash(self, image: Image.Image) -> str:
        """"
        簡單的計算圖片的感知哈希值，用來判斷畫面是不是有變化
        """
        image = image.convert("L").resize((16, 16))
        pixels = list(image.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if pixel > avg else "0" for pixel in pixels)
        return f"{int(bits, 2):064x}"
