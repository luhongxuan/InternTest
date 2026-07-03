# notepad_agent_local.py
import pyautogui
import subprocess
import time
import json
import base64
from PIL import ImageGrab
import ollama

# ============ 設定 ============
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

MODEL_NAME = "qwen2.5vl:7b"  # 或 "qwen2.5-vl:7b" 看 ollama 實際名稱

def capture_screen_base64():
    """截圖並轉成 base64 給 Ollama"""
    screenshot = ImageGrab.grab()
    # 縮小加速
    screenshot.thumbnail((1280, 800))
    
    import io
    buffer = io.BytesIO()
    screenshot.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8'), screenshot.size

def ask_local_vision_model(prompt: str):
    """
    讓本地 Vision 模型看螢幕
    """
    image_b64, size = capture_screen_base64()
    
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {
                'role': 'user',
                'content': prompt,
                'images': [image_b64]
            }
        ],
        format='json',  # 強制 JSON 回應
        options={
            'temperature': 0.1,  # 決策任務要穩定
            'num_predict': 500,   # 限制輸出長度
        }
    )
    
    decision = json.loads(response['message']['content'])
    
    # 座標轉換
    if decision.get('action') == 'click' and 'x' in decision:
        actual_size = pyautogui.size()
        decision['real_x'] = decision['x'] * (actual_size.width / size[0])
        decision['real_y'] = decision['y'] * (actual_size.height / size[1])
    
    return decision

def check_dialog_exists(dialog_image_path: str, confidence: float = 0.7):
    """圖片比對檢查對話框"""
    try:
        location = pyautogui.locateOnScreen(
            dialog_image_path,
            confidence=confidence
        )
        return location is not None
    except:
        return False

def find_and_click_image(image_path: str, confidence: float = 0.9):
    """找圖片並點擊"""
    try:
        location = pyautogui.locateOnScreen(image_path, confidence=confidence)
        if location:
            print("  ✓ 找到圖片，點擊中...")
            center = pyautogui.center(location)
            pyautogui.moveTo(center.x, center.y, duration=0.8)
            pyautogui.click()
            return True
    except Exception as e:
        print(f"錯誤：{e}")
        return False

# ============ 主任務 ============

def main_task():
    print("=" * 60)
    print("記事本自動化 Demo（本地模型版）")
    print(f"使用模型：{MODEL_NAME}")
    print("=" * 60)
    print("\n3 秒後開始...")
    time.sleep(3)
    
    # 開啟 test.txt
    print("\n[階段 1] 開啟 test.txt")
    test_file_path = r"C:\Users\luhon\Desktop\test.txt"
    subprocess.Popen(['notepad.exe', test_file_path])
    time.sleep(2)
    
    # 讓本地模型看螢幕決定要輸入什麼
    print("\n[階段 2] 本地 Vision 模型分析畫面")
    
    pyautogui.hotkey('ctrl', 'end')
    time.sleep(0.5)
    # pyautogui.press('enter')
    
#     decision = ask_local_vision_model("""
# 你看到的是記事本畫面。
# 請決定要在文件末尾輸入什麼內容,建議是一段自動化執行的記錄。

# 回傳 JSON:
# {
#     "action": "type",
#     "text": "要輸入的文字",
#     "reason": "為什麼輸入這個",
#     "screen_description": "現在畫面上看到什麼"
# }
# """)
    
#     print(f"  畫面：{decision.get('screen_description', '')}")
#     print(f"  決定輸入：{decision.get('text', '')}")
    
#     if decision.get('action') == 'type':
#         import pyperclip
#         pyperclip.copy(decision['text'])
#         pyautogui.hotkey('ctrl', 'v')
    
#     time.sleep(1)
    
    # 儲存
    print("\n[階段 3] 儲存檔案")
    pyautogui.hotkey('ctrl', 's')
    time.sleep(1.5)
    
    # 檢查儲存對話框
    print("\n[階段 4] 檢查儲存對話框")
    if check_dialog_exists('save_dialog.png'):
        print("  ✓ 偵測到對話框,按 Enter")
        pyautogui.press('enter')
        time.sleep(1)
    else:
        print("  ✗ 沒有對話框,略過")
    
    # 關閉
    print("\n[階段 5] 關閉視窗")
    # print(find_and_click_image('close_button.png'))
    while not find_and_click_image('close_button.png'):
        print(find_and_click_image('close_button.png'))
        time.sleep(0.5)
    print("  ✓ 已點擊叉叉")
    # else:
    #     pyautogui.hotkey('alt', 'f4')
    
    time.sleep(1)
    
    # 再次檢查
    if check_dialog_exists('save_dialog.png'):
        pyautogui.press('enter')
    
    print("\n" + "=" * 60)
    print("任務完成！")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main_task()
    except Exception as e:
        print(f"錯誤：{e}")
        import traceback
        traceback.print_exc()