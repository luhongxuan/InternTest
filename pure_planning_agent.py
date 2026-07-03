# pure_planning_agent.py
import pyautogui
import subprocess
import time
import json
import os
import pyperclip
from PIL import ImageGrab
import ollama

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

# 用純文字模型做規劃(不用 Vision,規劃階段不需要看畫面)
PLANNER_MODEL = "qwen2.5:7b"

# 執行時如果需要看畫面才用 Vision
VISION_MODEL = "qwen2.5vl:7b"


class PurePlanningAgent:
    """
    真正的 zero-shot Agent
    沒有手冊、沒有模板,只有一組可用的動作
    Agent 自己規劃整個任務
    """
    
    def __init__(self):
        self.ui_elements_dir = "ui_elements"
    
    def execute_task(self, user_request: str):
        print("=" * 70)
        print(f"使用者需求:{user_request}")
        print("=" * 70)
        
        # ===== 階段 1:Agent 自己規劃 =====
        print("\n[規劃階段] Agent 從零開始思考執行步驟...")
        print("  → 使用純文字模型進行規劃(不看畫面,純推理)")
        
        start = time.time()
        plan = self._make_plan(user_request)
        print(f"  → 規劃耗時:{time.time() - start:.1f} 秒")
        
        if not plan:
            print("  ✗ Agent 無法規劃出可執行的步驟")
            return
        
        print(f"\n{'─' * 70}")
        print("Agent 的計畫:")
        print(f"{'─' * 70}")
        for i, step in enumerate(plan, 1):
            print(f"\n  [第 {i} 步] {step['action']}")
            print(f"    目的: {step['purpose']}")
            print(f"    參數: {step.get('params', '(無)')}")
        
        # ===== 階段 2:確認執行 =====
        print(f"\n{'─' * 70}")
        input("按 Enter 開始執行這個計畫,或 Ctrl+C 取消...")
        
        # ===== 階段 3:照計畫執行 =====
        print(f"\n{'=' * 70}")
        print("開始執行")
        print(f"{'=' * 70}")
        
        for i, step in enumerate(plan, 1):
            print(f"\n{'─' * 70}")
            print(f"[執行 {i}/{len(plan)}] {step['action']}")
            print(f"  目的: {step['purpose']}")
            
            success = self._execute_step(step)
            
            if not success:
                print(f"  ✗ 執行失敗")
                
                # 讓 Agent 決定要不要繼續
                should_continue = self._decide_continuation(step, plan[i:])
                if not should_continue:
                    print("  Agent 決定中止任務")
                    return
        
        print(f"\n{'=' * 70}")
        print("計畫執行完畢")
        print(f"{'=' * 70}")
    
    def _make_plan(self, user_request: str) -> list:
        """
        讓 Agent 自己規劃
        """
        
        prompt = f"""你是一個電腦操作 Agent,你要根據使用者的需求,規劃一系列電腦操作步驟。

【使用者的需求】
{user_request}

【你可以用的動作】

1. open_program
   說明:開啟一個程式或檔案
   參數:程式的完整命令,例如 "notepad.exe C:\\path\\to\\file.txt"

2. hotkey
   說明:按組合鍵
   參數:按鍵陣列,例如 ["ctrl", "s"] 或 ["ctrl", "end"]

3. press_key
   說明:按單一按鍵
   參數:按鍵名稱,例如 "enter", "esc", "tab"

4. type_text
   說明:輸入一段文字
   參數:要輸入的文字內容

5. click_image
   說明:找到螢幕上的某個 UI 元件(按鈕、對話框)並點擊
   參數:元件名稱。目前可用的:"close_button"

6. wait
   說明:等待畫面反應
   參數:秒數,例如 2

7. check_and_handle_dialog
   說明:檢查是否有指定的對話框跳出,如果有就按 Enter 處理它
   參數:對話框名稱。目前可用的:"save_confirm_dialog"

【常識提示】
- Windows 的記事本可以用 notepad.exe 開啟
- 移動游標到文件末尾用 Ctrl+End
- 儲存檔案用 Ctrl+S
- 記事本沒有預先開啟儲存過的檔案,關閉時可能會跳出詢問是否儲存的對話框
- 開啟程式後需要等待幾秒讓它載入
- 按 Ctrl+S 之後也需要等待,可能會有儲存對話框

【你的任務】
根據使用者的需求,想出一系列步驟來達成目標。

【重要規則】
1. 不要重複做同樣的事
2. 考慮每個動作之後畫面會變成什麼樣子
3. 有些動作之後可能會有對話框跳出,要考慮處理
4. 每個步驟都要有明確的目的
5. 只用上面列出的動作,不要發明新動作

請以 JSON 格式回傳你的計畫:
{{
    "overall_strategy": "你整體的執行策略",
    "steps": [
        {{
            "action": "動作名稱",
            "params": "參數(依動作類型不同)",
            "purpose": "這一步要達成什麼"
        }}
    ]
}}
"""
        
        response = ollama.chat(
            model=PLANNER_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format='json',
            options={
                'temperature': 0.3,
                'num_predict': 2000,
            },
            keep_alive="10m"
        )
        
        try:
            result = json.loads(response['message']['content'])
            print(f"\n  Agent 的整體策略:")
            print(f"    {result.get('overall_strategy', '未說明')}")
            return result.get('steps', [])
        except Exception as e:
            print(f"  ⚠️ 規劃解析失敗: {e}")
            print(f"  原始回應: {response['message']['content'][:500]}")
            return []
    
    def _execute_step(self, step: dict) -> bool:
        action = step['action']
        params = step.get('params', '')
        
        print(f"  → 執行動作: {action}({params})")
        
        try:
            if action == 'open_program':
                subprocess.Popen(params.split())
                return True
            
            elif action == 'hotkey':
                keys = params if isinstance(params, list) else json.loads(params.replace("'", '"'))
                pyautogui.hotkey(*keys)
                return True
            
            elif action == 'press_key':
                pyautogui.press(params)
                return True
            
            elif action == 'type_text':
                if any('\u4e00' <= c <= '\u9fff' for c in params):
                    pyperclip.copy(params)
                    pyautogui.hotkey('ctrl', 'v')
                else:
                    pyautogui.typewrite(params, interval=0.05)
                return True
            
            elif action == 'wait':
                time.sleep(float(params))
                return True
            
            elif action == 'click_image':
                image_path = os.path.join(self.ui_elements_dir, f"{params}.png")
                if not os.path.exists(image_path):
                    print(f"    ⚠️ 找不到圖片: {image_path}")
                    return False
                
                location = pyautogui.locateOnScreen(image_path, confidence=0.7)
                if location:
                    center = pyautogui.center(location)
                    pyautogui.moveTo(center.x, center.y, duration=0.8)
                    pyautogui.click()
                    print(f"    ✓ 點擊了 {params}")
                    return True
                else:
                    print(f"    ⚠️ 螢幕上找不到 {params}")
                    return False
            
            elif action == 'check_and_handle_dialog':
                image_path = os.path.join(self.ui_elements_dir, f"{params}.png")
                if not os.path.exists(image_path):
                    print(f"    ⚠️ 找不到對話框圖片")
                    return False
                
                location = pyautogui.locateOnScreen(image_path, confidence=0.7)
                if location:
                    print(f"    ✓ 偵測到對話框,按 Enter 確認")
                    pyautogui.press('enter')
                    time.sleep(1)
                else:
                    print(f"    ✗ 沒有對話框,跳過此步")
                return True
            
            else:
                print(f"    ⚠️ 未知的動作: {action}")
                return False
        
        except Exception as e:
            print(f"    ✗ 執行時發生錯誤: {e}")
            return False
    
    def _decide_continuation(self, failed_step, remaining_steps):
        """失敗時,讓 Agent 決定要不要繼續"""
        print(f"  Agent 分析:失敗的步驟是「{failed_step['purpose']}」")
        # 簡單邏輯:如果只是找不到 UI 元件,就繼續執行下一步(可能對話框沒出現是正常的)
        return True


# ============ 主程式 ============

if __name__ == "__main__":
    agent = PurePlanningAgent()
    
    # 完全用自然語言描述需求,不給任何步驟提示
    user_request = """
我要在 C:\\Users\\luhon\\Desktop\\test.txt 這個檔案的末尾加入一段文字,
內容是「AI 自動化執行測試」。
加完之後幫我儲存並關閉這個檔案。
"""
    
    print("3 秒後開始...")
    time.sleep(3)
    
    agent.execute_task(user_request)