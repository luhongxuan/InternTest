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
    def __init__(self, model_max_width: int = 1280):
        self.sct = mss.MSS()
        if len(self.sct.monitors) > 2:
            self.monitor = self.sct.monitors[1]
        else:
            self.monitor = self.sct.monitors[1]
        self.model_max_width = 