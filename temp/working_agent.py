# working_agent.py
import pyautogui
import subprocess
import time
import json
import base64
import io
import os
from PIL import ImageGrab
import ollama
import pyperclip

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

MODEL_NAME = "qwen2.5vl:7b"


class SimpleAgent:
    
    def __init__(self):
        self.model = MODEL_NAME
        self.ui_elements_dir = "ui_elements"
    
    def ask_agent_for_text(self, purpose: str) -> str:
        """讓 Agent 決定要輸入什麼文字"""
        response = ollama.chat(
            model=self.model,
            messages=[{
                'role': 'user',
                'content': f"{purpose}\n\n請只回傳要輸入的文字內容,不要加任何說明。"
            }],
            options={'temperature': 0.7},
            keep_alive="10m"
        )
        return response['message']['content'].strip()
    
    def ask_agent_about_screen(self, question: str) -> dict:
        """讓 Agent 看螢幕回答問題"""
        screenshot = ImageGrab.grab()
        screenshot.thumbnail((1280, 800))
        
        buffer = io.BytesIO()
        screenshot.save(buffer, format='PNG')
        image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        response = ollama.chat(
            model=self.model,
            messages=[{
                'role': 'user',
                'content': f'''請看這張螢幕截圖,回答:
{question}

只回傳 JSON:{{"answer": "yes" 或 "no", "reason": "你的觀察"}}
''',
                'images': [image_b64]
            }],
            format='json',
            options={'temperature': 0.1},
            keep_alive="10m"
        )
        
        try:
            return json.loads(response['message']['content'])
        except:
            return {'answer': 'no', 'reason': '解析失敗'}
    
    def click_image(self, image_name: str, confidence: float = 0.7) -> bool:
        """用圖片匹配點擊"""
        image_path = os.path.join(self.ui_elements_dir, f"{image_name}.png")
        
        if not os.path.exists(image_path):
            print(f"  找不到圖片:{image_path}")
            return False
        
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                pyautogui.moveTo(center.x, center.y, duration=0.8)
                pyautogui.click()
                print(f"  點擊了 {image_name},座標 {center}")
                return True
            else:
                print(f"  螢幕上找不到 {image_name}")
                return False
        except Exception as e:
            print(f"  圖片匹配失敗:{e}")
            return False
    
    def type_text(self, text: str):
        """輸入文字"""
        if any('\u4e00' <= c <= '\u9fff' for c in text):
            pyperclip.copy(text)
            pyautogui.hotkey('ctrl', 'v')
        else:
            pyautogui.typewrite(text, interval=0.05)
        print(f"  輸入了:{text}")
    
    def execute(self, file_path: str):
        print("=" * 70)
        print("AI 自動化 Demo:記事本操作")
        print("=" * 70)
        
        print(f"\n[步驟 1] 開啟檔案:{file_path}")
        subprocess.Popen(['notepad.exe', file_path])
        time.sleep(2)
        print("  已開啟記事本")
        
        print(f"\n[步驟 2] Agent 決定要輸入的內容")
        print("  Agent 思考中...")
        
        start = time.time()
        text_to_type = self.ask_agent_for_text(
            f"我要在 test.txt 檔案末尾加入一段自動化執行的記錄。"
            f"目前時間是 {time.strftime('%Y-%m-%d %H:%M:%S')}。"
            f"請幫我想一段簡短的訊息,10-30 個字,包含執行時間。"
        )
        print(f"  思考耗時:{time.time() - start:.1f} 秒")
        print(f"  Agent 決定輸入:「{text_to_type}」")
        
        print(f"\n[步驟 3] 移到文件末尾並輸入文字")
        pyautogui.hotkey('ctrl', 'end')
        time.sleep(0.5)
        pyautogui.press('enter')
        time.sleep(0.3)
        self.type_text(text_to_type)
        time.sleep(1)
        
        print(f"\n[步驟 4] 儲存檔案 (Ctrl+S)")
        pyautogui.hotkey('ctrl', 's')
        time.sleep(1.5)
        print("  已按 Ctrl+S")
        
        print(f"\n[步驟 5] Agent 判斷是否有儲存對話框")
        print("  Agent 看畫面中...")
        
        start = time.time()
        result = self.ask_agent_about_screen(
            "畫面上是否有跳出一個對話框在問要不要儲存變更?"
        )
        print(f"  判斷耗時:{time.time() - start:.1f} 秒")
        print(f"  Agent 判斷:{result['answer']} ({result.get('reason', '')})")
        
        if result['answer'] == 'yes':
            print("  按 Enter 確認儲存")
            pyautogui.press('enter')
            time.sleep(1)
        
        print(f"\n[步驟 6] 關閉記事本視窗")
        
        if not self.click_image("close_button"):
            print("  改用 Alt+F4 關閉")
            pyautogui.hotkey('alt', 'f4')
        
        time.sleep(1.5)
        
        print(f"\n[步驟 7] Agent 再次判斷是否有儲存對話框")
        
        start = time.time()
        result = self.ask_agent_about_screen(
            "畫面上是否有跳出一個對話框在問要不要儲存變更?"
        )
        print(f"  判斷耗時:{time.time() - start:.1f} 秒")
        print(f"  Agent 判斷:{result['answer']}")
        
        if result['answer'] == 'yes':
            print("  按 Enter 確認儲存")
            pyautogui.press('enter')
            time.sleep(1)
        
        print("\n" + "=" * 70)
        print("任務完成!")
        print("=" * 70)


if __name__ == "__main__":
    agent = SimpleAgent()
    
    file_path = r"C:\Users\luhon\Desktop\test.txt"
    
    print("3 秒後開始...")
    time.sleep(3)
    
    agent.execute(file_path)