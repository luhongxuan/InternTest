# real_agent_v2.py
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

# ============ 設定 ============
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

MODEL_NAME = "qwen2.5vl:7b"

# ============ 圖片素材庫 ============

class ImageLibrary:
    """
    管理所有已知的 UI 元素圖片
    Agent 可以查詢「有哪些已知按鈕」,然後決定要點哪一個
    """
    
    def __init__(self, image_dir: str = "ui_elements"):
        self.image_dir = image_dir
        self.elements = self._scan_images()
        self.descriptions = {
            'close_button': {
                'purpose': '記事本視窗右上角的關閉按鈕(X)',
                'when_to_use': '當你想關閉記事本視窗時',
                'action_type': '點擊'
            },
            'save_confirm_dialog': {
                'purpose': '關閉記事本時跳出的「儲存變更嗎?」對話框',
                'when_to_use': '只用來檢查對話框是否出現(用 check_element_exists),不要用來點擊，在儲存時不一定會出現這個對話框，只要是之前有儲存過的就不會出現',
                'action_type': '檢查(不點擊)'
            }
        }
    
    def _scan_images(self):
        """掃描資料夾裡所有的圖片,建立索引"""
        elements = {}
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)
            return elements
        
        for filename in os.listdir(self.image_dir):
            if filename.endswith(('.png', '.jpg')):
                # 檔名去掉副檔名當作元件名稱
                name = os.path.splitext(filename)[0]
                elements[name] = os.path.join(self.image_dir, filename)
        
        return elements

    def get_element_description(self):
        """給 Agent 看的元件說明"""
        text = "圖片庫中的可用元件及其用途:\n\n"
        for name, path in self.elements.items():
            desc = self.descriptions.get(name, {})
            text += f"【{name}】\n"
            text += f"  用途:{desc.get('purpose', '未定義')}\n"
            text += f"  何時使用:{desc.get('when_to_use', '未定義')}\n"
            text += f"  動作類型:{desc.get('action_type', '未定義')}\n\n"
        return text
    
    def get_available_elements(self):
        """回傳所有可用的元件名稱給 Agent 參考"""
        return list(self.elements.keys())
    
    def get_path(self, element_name: str):
        """取得元件的圖片路徑"""
        return self.elements.get(element_name)

# ============ Agent 可以用的工具 ============

class AgentTools:
    
    def __init__(self, image_library: ImageLibrary):
        self.image_lib = image_library
    
    def capture_screen(self):
        """截圖並回傳 base64 和尺寸"""
        screenshot = ImageGrab.grab()
        screenshot.thumbnail((1280, 800))
        
        buffer = io.BytesIO()
        screenshot.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue()).decode('utf-8'), screenshot.size
    
    def click_by_image(self, element_name: str, confidence: float = 0.8):
        """
        用圖片匹配找元件並點擊(高精度)，如果要關閉應用程式可以使用這個來點擊右上角的叉叉來關閉
        這是 Agent 最推薦用的點擊方式，但是如果你看了每一個圖片的description發現沒有對應的就不要硬要用這個，請使用click_by_coordinates完成
        """
        print(f"  → 嘗試用圖片匹配點擊 {element_name} (信心度 {confidence})")
        image_path = self.image_lib.get_path(element_name)
        
        if not image_path:
            return {
                'success': False,
                'message': f"找不到元件圖片:{element_name}。可用元件:{self.image_lib.get_available_elements()}"
            }
        
        try:
            location = pyautogui.locateOnScreen(
                image_path,
                confidence=confidence
            )
            
            if location:
                center = pyautogui.center(location)
                # 慢慢移動讓 demo 看得見
                pyautogui.moveTo(center.x, center.y, duration=0.8)
                pyautogui.click()
                return {
                    'success': True,
                    'message': f"用圖片匹配點擊了 {element_name},座標 ({center.x}, {center.y})"
                }
            else:
                return {
                    'success': False,
                    'message': f"在螢幕上找不到 {element_name}(信心度 {confidence})"
                }
        
        except Exception as e:
            return {
                'success': False,
                'message': f"圖片匹配失敗:{e}"
            }
    
    def click_by_coordinates(self, x: int, y: int, screen_size: tuple):
        """
        用座標點擊(低精度,備援方案)
        當圖片素材庫沒有對應元件時才用這個
        """
        actual = pyautogui.size()
        real_x = x * (actual.width / screen_size[0])
        real_y = y * (actual.height / screen_size[1])
        
        pyautogui.moveTo(real_x, real_y, duration=0.8)
        pyautogui.click()
        return {
            'success': True,
            'message': f"用座標點擊了 ({real_x:.0f}, {real_y:.0f})"
        }
    
    def check_element_exists(self, element_name: str, confidence: float = 0.8):
        """
        檢查某個元件是否出現在螢幕上(不點擊)
        回傳True代表元件存在
        遇到False代表元件不存在，這個時候請自行思考下一步要做甚麼，不要一直在這裡檢查元件有沒有出現
        Agent 可以用這個確認畫面狀態
        """
        image_path = self.image_lib.get_path(element_name)
        
        if not image_path:
            return {
                'exists': False,
                'message': f"元件 {element_name} 不在圖片庫中"
            }
        
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            return {
                'exists': location is not None,
                'message': f"{'找到' if location else '找不到'} {element_name}"
            }
        except:
            return {'exists': False, 'message': f"檢查 {element_name} 時出錯"}
    
    def type_text(self, text: str):
        """
        輸入文字,如果有中文就先複製再貼上,避免中文亂碼
        Agent 可以用這個輸入文字到記事本或其他程式
        """
        if any('\u4e00' <= c <= '\u9fff' for c in text):
            pyperclip.copy(text)
            pyautogui.hotkey('ctrl', 'v')
        else:
            pyautogui.typewrite(text, interval=0.05)
        return {'success': True, 'message': f"輸入了:{text[:30]}..."}
    
    def press_key(self, key: str):
        """
        按單一按鍵,例如 "enter", "tab", "esc"
        Agent 可以用這個來操作對話框或快捷鍵
        """
        pyautogui.press(key)
        return {'success': True, 'message': f"按了:{key}"}
    
    def hotkey(self, *keys):
        """
        按組合鍵,例如 ("ctrl", "s"), ("alt", "tab")
        Agent 可以用這個來操作對話框或快捷鍵
        """
        pyautogui.hotkey(*keys)
        return {'success': True, 'message': f"按了組合鍵:{' + '.join(keys)}"}
    
    def open_program(self, program: str):
        """
        開啟程式,例如 notepad.exe 或 C:\\path\\to\\app
        當需要開啟檔案時,可以直接給完整路徑來開啟應用程式
        """
        subprocess.Popen(program.split())
        return {'success': True, 'message': f"開啟了:{program}"}
    
    def wait(self, seconds: float):
        """
        等待指定秒數
        Agent 可以用這個來等待畫面更新或對話框出現
        """
        time.sleep(seconds)
        return {'success': True, 'message': f"等待了 {seconds} 秒"}

# ============ Agent 核心 ============

class ComputerUseAgent:
    
    def __init__(self, model_name: str = MODEL_NAME):
        self.model = model_name
        self.image_lib = ImageLibrary("ui_elements")
        self.tools = AgentTools(self.image_lib)
        self.history = []
        self.max_steps = 30
    
    def execute_task(self, task_description: str):
        print("=" * 70)
        print(f"任務:{task_description}")
        print(f"圖片庫中可用元件:{self.image_lib.get_available_elements()}")
        print("=" * 70)
        
        for step in range(1, self.max_steps + 1):
            print(f"\n{'─' * 70}")
            print(f"[步驟 {step}]")
            
            image_b64, size = self.tools.capture_screen()
            
            print("  → Agent 思考中...")
            start = time.time()
            decision = self._make_decision(task_description, image_b64, size)
            print(f"  → 思考耗時:{time.time() - start:.1f} 秒")
            
            print(f"\n  Agent 觀察:{decision.get('screen_description', '')}")
            print(f"  Agent 分析:{decision.get('reasoning', '')}")
            print(f"  Agent 決定:{decision['action']}")
            
            if decision['action'] == 'task_complete':
                print(f"\n{'=' * 70}")
                print(f"✓ 任務完成:{decision.get('reasoning', '')}")
                print(f"{'=' * 70}")
                return True
            
            if decision['action'] == 'task_failed':
                print(f"\n{'=' * 70}")
                print(f"✗ 任務失敗:{decision.get('reasoning', '')}")
                print(f"{'=' * 70}")
                return False
            
            result = self._execute_action(decision, size)
            print(f"  執行結果:{result['message']}")
            
            self.history.append({
                'step': step,
                'action': decision['action'],
                'reasoning': decision.get('reasoning', ''),
                'result': result['message'],
                'success': result.get('success', True)
            })
            
            # 如果剛剛的動作失敗,讓 Agent 知道要換方法
            if not result.get('success', True):
                print(f"  ⚠ 動作失敗,Agent 下一步會嘗試調整")
            
            time.sleep(1)
        
        print(f"\n達到最大步驟數")
        return False
    
    def _make_decision(self, task: str, image_b64: str, screen_size: tuple):
        
        # 把歷史整理給 Agent 參考
        history_text = ""
        if self.history:

            history_text = f"""
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            重要:你已經執行了 {len(self.history)} 個動作,絕對不要重複做同樣的事!!!!!!!!!
            一定要看你已經做過什麼,再決定下一步要做什麼,不要重複做同樣的事!!!!!!!!!
            一件事只能做一次,不要重複做同樣的事!!!!!!!!!
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            【已執行的動作歷史】\n"""
            for h in self.history[-3:]:
                temp = ""
                status = "✓" if h['success'] else "✗"
                temp += f"{status} 步驟{h['step']}: {h['action']} - {h['reasoning']}\n"
                temp += f"   結果:{h['result']}\n"
                history_text += temp
                if history_text.count(h['action']) > 1:
                    history_text += "   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"
                    history_text += "   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"
                    history_text += "   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"
                    history_text += "   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"
                    history_text += "   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"+"   ⚠ 注意:這個動作已經做過了,不要重複做同樣的事!!!!!!!!請換成其他的動作!!!!!!!\n"
        
        # 告訴 Agent 有哪些預先準備的圖片可以用
        available_elements = self.image_lib.get_available_elements()
        elements_text = ""
        if available_elements:
            elements_text = f"""
【圖片素材庫】
以下是預先準備好的 UI 元件圖片,你可以用 click_by_image 精確點擊:
{', '.join(available_elements)}
{self.image_lib.get_element_description()}

重要:如果要點擊的元件在這個清單中,優先使用 click_by_image,
它是用圖片精確匹配的,比用座標點擊準確很多。

重要:
- close_button 是關閉按鈕,可以用 click_by_image 點擊
- save_confirm_dialog 是對話框,只用 check_element_exists 檢查它出現了沒,不要用 click_by_image 點它
- 儲存檔案不是點擊某個圖片,而是按 Ctrl+S 快捷鍵
"""
        
        prompt = f"""你是一個電腦操作 Agent,你的任務是:
{task}

{elements_text}

{history_text}

現在你看到的是螢幕截圖(縮圖尺寸 {screen_size[0]} x {screen_size[1]})。
螢幕的截圖一開始可能會有其他的程式，但請不要管他，繼續做你的任務就可以了。

你可以用的動作:

1. click_by_image - 用圖片匹配精確點擊已知元件(高精度)
   參數: element_name (必須是圖片庫中的元件名稱)
   例:{{"action": "click_by_image", "element_name": "close_button"}}

2. click_by_coordinates - 用座標點擊(低精度,只在圖片庫沒有時用)
   參數: x, y

3. check_element_exists - 檢查某元件是否出現(不點擊)
   參數: element_name
   
4. type_text - 輸入文字
   參數: text
   
5. press_key - 按單一按鍵
   參數: key (例如 "enter")
   
6. hotkey - 按組合鍵
   參數: keys (陣列,例如 ["ctrl", "s"])
   
7. open_program - 開啟程式
   參數: program
   
8. wait - 等待
   參數: seconds
   
9. task_complete - 任務完成
   
10. task_failed - 無法完成

【決策順序】
1. 先看任務要什麼(讀 task_description)
2. 再看歷史做到哪一步
3. 最後看畫面現在的狀態，一但達到目標狀態，立刻結束迴圈
4. 選對應的動作，如果做了這個動作後發現沒有達到目標狀態，下一步要想辦法調整策略，不要重複做錯誤的事

【重要】
- 不是每個動作都要用 click_by_image
- 開啟檔案要用 open_program,不是 click_by_image
- click_by_image 只用來點擊「按鈕、對話框」這類 UI 元件
- 儲存檔案請用 Ctrl+S 快捷鍵, 可以使用hotkey(["ctrl", "s"])

請回傳 JSON:
{{
    "screen_description": "描述你看到的畫面",
    "reasoning": "為什麼這樣決定",
    "action": "動作名稱",
    "element_name": "元件名稱(如果用 click_by_image 或 check_element_exists)",
    "x": 座標(如果用 click_by_coordinates),
    "y": 座標(如果用 click_by_coordinates),
    "text": "文字(如果用 type_text)",
    "key": "按鍵(如果用 press_key)",
    "keys": ["按鍵陣列"](如果用 hotkey),
    "program": "程式路徑"(如果用 open_program),
    "seconds": 秒數(如果用 wait)
}}
"""
        
        print(prompt)
        
        response = ollama.chat(
            model=self.model,
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [image_b64]
            }],
            format='json',
            options={
                'temperature': 0.2,
                'num_predict': 800,
            },
            keep_alive="10m"
        )
        
        try:
            return json.loads(response['message']['content'])
        except json.JSONDecodeError:
            return {
                'action': 'task_failed',
                'reasoning': 'Agent 回應解析失敗'
            }
    
    def _execute_action(self, decision: dict, screen_size: tuple):
        action = decision['action']
        
        try:
            if action == 'click_by_image':
                return self.tools.click_by_image(decision['element_name'])
            
            elif action == 'click_by_coordinates':
                return self.tools.click_by_coordinates(
                    decision['x'], decision['y'], screen_size
                )
            
            elif action == 'check_element_exists':
                result = self.tools.check_element_exists(decision['element_name'])
                return {
                    'success': True,
                    'message': result['message'] + f" (存在:{result['exists']})"
                }
            
            elif action == 'type_text':
                return self.tools.type_text(decision['text'])
            
            elif action == 'press_key':
                return self.tools.press_key(decision['key'])
            
            elif action == 'hotkey':
                return self.tools.hotkey(*decision['keys'])
            
            elif action == 'open_program':
                return self.tools.open_program(decision['program'])
            
            elif action == 'wait':
                return self.tools.wait(decision['seconds'])
            
            else:
                return {'success': False, 'message': f"未知動作:{action}"}
        
        except Exception as e:
            return {'success': False, 'message': f"執行失敗:{e}"}

# ============ 主程式 ============

if __name__ == "__main__":
    
    # 確保有這個資料夾,把你之前截的圖放進去
    # ui_elements/close_button.png
    # ui_elements/save_dialog.png
    
    agent = ComputerUseAgent()
    
    task = r"""
    請幫我完成以下任務:
    1. 開啟桌面上的 C:\\Users\\luhon\\Desktop\\test.txt 檔案(用記事本開啟)
       路徑範例:notepad.exe C:\\Users\\luhon\\Desktop\\test.txt
    2. 在檔案末尾加入一句文字,內容是「AI 自動化執行測試」
    3. 儲存檔案
    4. 如果跳出儲存對話框,按 Enter 確認
    5. 關閉記事本視窗

    點擊按鈕時可以使用圖片匹配(click_by_image)或座標點擊(click_by_coordinates),優先使用圖片匹配。
    """
    
    print("3 秒後開始...")
    time.sleep(3)
    
    success = agent.execute_task(task)
    print(f"\n結果:{'成功' if success else '失敗'}")