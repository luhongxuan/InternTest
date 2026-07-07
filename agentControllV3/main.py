import pyautogui
import time
import json
import base64
import io
import os
import mss
from PIL import Image
import ollama
import pyperclip

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1

VISION_MODEL = "qwen2.5vl:7b" 
PLANNER_MODEL = "qwen2.5:14b"

# class ImageLibrary:
#     def __init__(self, image_path: str = "ui_elementes"):
        

class AgentTools:
    def __init__(self):
        self.sct = mss.MSS()
        if len(self.sct.monitors) > 2:
            self.monitor = self.sct.monitors[1]
        else:
            self.monitor = self.sct.monitors[1]
        

    def capture_screen(self):
        sct_image = self.sct.grab(self.monitor)

        self.screenshot = Image.frombytes("RGB", sct_image.size, sct_image.rgb, "raw", "BGRX")
        self.screenshot.thumbnail((1280, 800))
        self.screenshot.save("screenshot.png")

        buffer = io.BytesIO()

        