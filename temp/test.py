import pyautogui
import subprocess
import time
import json
import base64
import io
import os
import mss
import base64
import ollama
import pyperclip
from PIL import Image

# 引入你的操作手冊與知識庫
from notepad_manual import NOTEPAD_PROCEDURES
from knowledge_base import ProcedureKnowledgeBase

# ============ 設定 ============
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

# 視覺模型：負責看截圖執行動作
VISION_MODEL = "qwen2.5vl:7b" 
# 文字模型：負責一開始排定計畫 (用 7b 純文字比較快，也可共用 VL)
PLANNER_MODEL = "qwen2.5:7b"  

# ============ 圖片素材庫與工具 (保留你原本的優良設計) ============

class ImageLibrary:
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
                'when_to_use': '只用來檢查對話框是否出現',
                'action_type': '檢查(不點擊)'
            }
        }
    
    def _scan_images(self):
        elements = {}
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)
            return elements
        for filename in os.listdir(self.image_dir):
            if filename.endswith(('.png', '.jpg')):
                name = os.path.splitext(filename)[0]
                elements[name] = os.path.join(self.image_dir, filename)
        return elements

    def get_element_description(self):
        text = "圖片庫中的可用元件及其用途:\n"
        for name, path in self.elements.items():
            desc = self.descriptions.get(name, {})
            text += f"- 【{name}】: {desc.get('purpose', '未定義')}\n"
        return text
    
    def get_available_elements(self):
        return list(self.elements.keys())
    
    def get_path(self, element_name: str):
        return self.elements.get(element_name)

class AgentTools:
    def __init__(self, image_library: ImageLibrary):
        self.image_lib = image_library
    
    def capture_screen(self):
        """使用 mss 鎖定第二螢幕截圖"""
        with mss.mss() as sct:
            if len(sct.monitors) > 2:
                monitor = sct.monitors[2] 
            else:
                print("  [系統] 未偵測到第二螢幕，自動切換為主螢幕截圖。")
                monitor = sct.monitors[1] 

            sct_img = sct.grab(monitor)

            screenshot = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            screenshot.thumbnail((1280, 800)) 
            
            buffer = io.BytesIO()
            screenshot.save(buffer, format='PNG')
            return base64.b64encode(buffer.getvalue()).decode('utf-8'), screenshot.size
    
    def click_by_image(self, element_name: str, confidence: float = 0.8):
        print(f"  → 嘗試用圖片匹配點擊 {element_name}")
        image_path = self.image_lib.get_path(element_name)
        if not image_path:
            return {'success': False, 'message': f"找不到元件圖片:{element_name}"}
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                pyautogui.moveTo(center.x, center.y, duration=0.8)
                pyautogui.click()
                return {'success': True, 'message': f"點擊了 {element_name}"}
            return {'success': False, 'message': f"畫面上找不到 {element_name}"}
        except Exception as e:
            return {'success': False, 'message': f"圖片匹配失敗:{e}"}
            
    def click_by_coordinates(self, x: int, y: int, screen_size: tuple):
        actual = pyautogui.size()
        real_x = x * (actual.width / screen_size[0])
        real_y = y * (actual.height / screen_size[1])
        pyautogui.moveTo(real_x, real_y, duration=0.8)
        pyautogui.click()
        return {'success': True, 'message': f"用座標點擊了 ({real_x:.0f}, {real_y:.0f})"}
    
    def check_element_exists(self, element_name: str, confidence: float = 0.8):
        image_path = self.image_lib.get_path(element_name)
        if not image_path:
            return {'exists': False, 'message': f"元件 {element_name} 不在圖片庫中"}
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            return {'exists': location is not None, 'message': f"{'找到' if location else '找不到'} {element_name}"}
        except:
            return {'exists': False, 'message': f"檢查 {element_name} 時出錯"}
    
    def type_text(self, text: str):
        if any('\u4e00' <= c <= '\u9fff' for c in text):
            pyperclip.copy(text)
            pyautogui.hotkey('ctrl', 'v')
        else:
            pyautogui.typewrite(text, interval=0.05)
        return {'success': True, 'message': f"輸入了:{text[:30]}..."}
    
    def press_key(self, key: str):
        pyautogui.press(key)
        return {'success': True, 'message': f"按了:{key}"}
    
    def hotkey(self, *keys):
        pyautogui.hotkey(*keys)
        return {'success': True, 'message': f"按了組合鍵:{' + '.join(keys)}"}
    
    def open_program(self, program: str):
        # 為了穩定，使用 win + r 來執行
        pyautogui.hotkey('win', 'r')
        time.sleep(0.5)
        pyautogui.typewrite(program)
        pyautogui.press('enter')
        return {'success': True, 'message': f"嘗試開啟:{program}"}
    
    def wait(self, seconds: float):
        time.sleep(seconds)
        return {'success': True, 'message': f"等待了 {seconds} 秒"}

# ============ 視覺與手冊混合 Agent 核心 ============

class VisionGuidedAgent:
    def __init__(self):
        self.image_lib = ImageLibrary("ui_elements")
        self.tools = AgentTools(self.image_lib)
        self.kb = ProcedureKnowledgeBase(NOTEPAD_PROCEDURES)
        
    def _generate_plan(self, task_description: str, dynamic_params: dict) -> list:
        print("\n[導航者] 正在根據任務規劃操作手冊順序...")
        prompt = f"""
                    你是本地端電腦操作 Agent 的高階 Planner。

                    你的工作：
                    根據使用者任務，從「可用 procedures」中選出需要執行的 procedure 順序。
                    你只能選 procedure id，不能選低階 action，例如 hotkey、type_text、click_by_image。

                    使用者任務：
                    {task_description}

                    已知參數：
                    {json.dumps(dynamic_params, ensure_ascii=False)}

                    可用 procedures：
                    {self.kb.get_all_procedures_summary()}

                    規劃規則：
                    1. 只能使用操作手冊中存在的 procedure id。
                    2. 不要自己發明 procedure id。
                    3. 如果任務要編輯檔案，通常需要 open_file。
                    4. 如果任務要追加文字，通常需要 add_text_to_end。
                    5. 如果任務要求保留修改，必須包含 save_file。
                    6. 如果任務要求最後關閉視窗，必須包含 close_notepad。
                    7. handle_save_dialog 只在「可能出現儲存確認對話框」時放在 close_notepad 後面。
                    8. 不要加入低階 action，例如 hotkey、press_key、type_text。
                    9. 不要重複同一個 procedure，除非它是 recovery 用途。

                    請只輸出 JSON，不要輸出其他文字。

                    輸出格式：
                    {{
                    "plan": [
                        {{
                        "procedure_id": "open_file",
                        "inputs": {{
                            "file_path": "..."
                        }},
                        "reason": "為了先開啟目標檔案"
                        }}
                    ],
                    "final_success_criteria": [
                        "目標檔案已開啟過",
                        "指定文字已加入檔案末尾",
                        "檔案已儲存",
                        "記事本已關閉"
                    ]
                    }}
                    """
        response = ollama.chat(
            model=PLANNER_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.1}
        )
        raw = response['message']['content'].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
        try:
            return json.loads(raw)
        except:
            print("[警告] 規劃失敗，使用預設安全計畫")
            return ["open_file", "add_text_to_end", "save_file", "close_notepad", "handle_save_dialog"]

    def execute_task(self, task_description: str, dynamic_params: dict):
        # 1. 產生高階計畫
        plan = self._generate_plan(task_description, dynamic_params)
        print(f"\n[系統] 高階執行計畫已確定: {plan}")
        
        current_state = {
            "overall_status": "running",
            "current_procedure": None,
            "procedures_completed": [],
        }

        # 2. 依序進入視覺迴圈
        for step_idx, procedure_id in enumerate(plan):
            proc = self.kb.get_procedure(procedure_id)
            if not proc:
                continue
                
            print(f"\n{'=' * 70}")
            print(f"[系統] 開始執行計畫 {step_idx + 1}/{len(plan)}: 【{proc['name']}】")
            print(f"{'=' * 70}")

            current_state["current_procedure"] = proc['id']

            current_step_index = 0
            completed_steps = []
            failed_attempts = 0
            last_action_result = {"status": "尚未開始執行"}

            # 在這個 Procedure 裡的視覺重試次數 (防止卡死)
            micro_step_count = 0 
            max_micro_steps = 15
            
            while micro_step_count < max_micro_steps:
                micro_step_count += 1
                image_b64, size = self.tools.capture_screen()
                
                decision = self._make_vision_decision(task, proc, dynamic_params, image_b64, size)
                
                print(f"  [視覺判定] {decision.get('reasoning', '')}")
                print(f"  [執行動作] {decision['action']}")
                
                if decision['action'] == 'advance_plan':
                    print(f"  ✓ 階段【{proc['name']}】完成，進入下一步！")
                    break # 跳出 while，進入下一個 procedure
                
                if decision['action'] == 'task_failed':
                    print(f"  ✗ 任務執行失敗。")
                    return False

                last_action_result = decision  # 記錄最後一次的 action 結果
                    
                # 執行動作
                self._execute_action(decision, size, dynamic_params)
                time.sleep(1.5) # 動作後等待畫面更新
                
            if micro_step_count >= max_micro_steps:
                print(f"  ⚠ 在【{proc['name']}】卡住太久，強制進入下一階段。")

        print("\n🎉 整個規劃已全部執行完畢！")
        return True
        
    def _make_vision_decision(self, task: str, proc: dict, dynamic_params: dict, image_b64: str, size: tuple):
        # 把 params_template 裡面的變數替換成實際值，給 Agent 參考
        suggested_steps = json.dumps(proc['steps'], ensure_ascii=False)
        for key, val in dynamic_params.items():
            suggested_steps = suggested_steps.replace(f"{{{key}}}", str(val))
            
        prompt = f"""
                    你是本地端電腦操作 Agent 的 Procedure Step Executor。

                    你不是 Planner。
                    你不能自由重新規劃任務。
                    你只能根據目前 procedure 的 steps，決定下一個要執行的低階 action。

                    目前使用者任務：
                    {task}

                    目前 procedure：
                    {proc["id"]} - {proc["name"]}

                    procedure 目標：
                    {proc["description"]}

                    procedure steps：
                    {suggested_steps}

                    目前 procedure 的執行進度：
                    - current_step_index: {current_step_index}
                    - completed_steps: {completed_steps}
                    - failed_attempts: {failed_attempts}

                    目前任務狀態：
                    {json.dumps(current_state, ensure_ascii=False)}

                    上一個 action 的執行結果：
                    {json.dumps(last_action_result, ensure_ascii=False)}

                    你現在看到的是螢幕截圖。

                    你的工作：
                    1. 判斷目前畫面是否符合 current_step 的執行條件。
                    2. 如果 current_step 尚未完成，請執行 current_step 指定的 action。
                    3. 如果 current_step 已經完成，請回傳 advance_step。
                    4. 只有在 procedure 的所有 steps 都完成，而且 success_checks 也成立時，才可以回傳 advance_plan。
                    5. 如果畫面被儲存確認對話框擋住，且目前 procedure 不是 handle_save_dialog，請回傳 need_recovery。
                    6. 不要重複執行已完成的 step。
                    7. 不要自己發明 procedure 或 action。
                    8. 不要因為「看起來差不多」就提早 advance_plan。

                    可用 action：
                    - click_by_image
                    - click_by_coordinates
                    - check_element_exists
                    - type_text
                    - press_key
                    - hotkey
                    - open_program
                    - wait
                    - advance_step
                    - advance_plan
                    - need_recovery
                    - task_failed

                    圖片庫：
                    {self.image_lib.get_element_description()}

                    請只輸出 JSON，不要輸出其他文字。

                    輸出格式：
                    {{
                    "reasoning": "根據畫面與目前 step，我判斷...",
                    "action": "動作名稱",
                    "step_id": "目前要執行或完成的 step_id",
                    "element_name": null,
                    "x": null,
                    "y": null,
                    "text": null,
                    "key": null,
                    "keys": null,
                    "program": null,
                    "seconds": null,
                    "confidence": 0.0,
                    "expected_result": "執行後應該看到或發生什麼"
                    }}
                    """
        response = ollama.chat(
            model=VISION_MODEL,
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [image_b64]
            }],
            format='json',
            options={'temperature': 0.1, 'num_predict': 500}
        )
        
        try:
            return json.loads(response['message']['content'])
        except json.JSONDecodeError:
            return {'action': 'wait', 'seconds': 1, 'reasoning': 'JSON解析失敗，等待重試'}

    def _execute_action(self, decision: dict, screen_size: tuple, dynamic_params: dict):
        action = decision['action']
        try:
            if action == 'click_by_image':
                return self.tools.click_by_image(decision.get('element_name'))
            elif action == 'click_by_coordinates':
                return self.tools.click_by_coordinates(decision.get('x',0), decision.get('y',0), screen_size)
            elif action == 'check_element_exists':
                return self.tools.check_element_exists(decision.get('element_name'))
            elif action == 'type_text':
                # 如果 LLM 沒有回傳 text，或者回傳了模板 {text}，就強制替換為動態參數
                text_to_type = decision.get('text', dynamic_params.get('text'))
                if '{text}' in text_to_type: text_to_type = dynamic_params.get('text')
                return self.tools.type_text(text_to_type)
            elif action == 'press_key':
                return self.tools.press_key(decision.get('key'))
            elif action == 'hotkey':
                return self.tools.hotkey(*decision.get('keys', []))
            elif action == 'open_program':
                prog = decision.get('program', '')
                if '{file_path}' in prog: prog = prog.replace('{file_path}', dynamic_params.get('file_path'))
                return self.tools.open_program(prog)
            elif action == 'wait':
                return self.tools.wait(decision.get('seconds', 1))
        except Exception as e:
            print(f"  [錯誤] 執行 {action} 發生例外: {e}")

# ============ 執行區塊 ============

if __name__ == "__main__":
    agent = VisionGuidedAgent()
    
    task = "開啟桌面的 test.txt，在最後面加上『AI 自動化執行測試』，儲存並關閉視窗。"
    
    # 將會變動的參數抽出來，避免 LLM 產生幻覺打錯字或路徑
    params = {
        "file_path": "C:\\Users\\luhon\\Desktop\\test.txt", 
        "text": f"AI 自動化執行測試 - 時間: {time.strftime('%H:%M:%S')}"
    }
    
    print("將在 3 秒後開始執行任務，請勿移動滑鼠...")
    time.sleep(3)
    
    agent.execute_task(task, params)