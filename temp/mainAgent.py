import pyautogui
import subprocess
import time
import json
import base64
import io
import os
import mss
from PIL import Image
import ollama
import pyperclip

# 引入你的操作手冊與知識庫
from agentControllV2.notepad_manual import NOTEPAD_PROCEDURES, AGENT_USAGE_RULES
from agentControllV2.knowledge_base import ProcedureKnowledgeBase

# ============ 設定 ============
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

VISION_MODEL = "qwen2.5vl:7b" 
PLANNER_MODEL = "qwen2.5:7b"  

# ============ 圖片素材庫與工具 ============
class ImageLibrary:
    def __init__(self, image_dir: str = "ui_elements"):
        self.image_dir = image_dir
        self.elements = self._scan_images()
        self.descriptions = {
            'close_button': {
                'purpose': '記事本視窗右上角的關閉按鈕(X)',
                'when_to_use': '當你想關閉記事本視窗時',
                'action_type': '點擊',
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
    
    def capture_screen(self, current_step_index: int = 0):
        """使用 mss 鎖定第二螢幕截圖"""
        with mss.MSS() as sct:
            if len(sct.monitors) > 2:
                monitor = sct.monitors[1] 
            else:
                print("  [系統] 未偵測到第二螢幕，自動切換為主螢幕截圖。")
                monitor = sct.monitors[1] 

            sct_img = sct.grab(monitor)

            screenshot = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            screenshot.thumbnail((1280, 800)) 

            screenshot.save(f"screenshot/screenshot.png")
            
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
        time.sleep(0.1)
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
        subprocess.Popen(program.split())
        return {'success': True, 'message': f"開啟了:{program}"}
    
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
                    {json.dumps(AGENT_USAGE_RULES["planning_rules"], ensure_ascii=False, indent=2)}

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
                        "檔案已儲存，確保這個筆記上方的分頁的圓形點點消失，表示已經儲存",
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
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "plan" in parsed:
                # 保留完整的 plan（包含 inputs 和 reason）
                return parsed["plan"]
            return parsed
        except Exception as e:
            print(f"[警告] 規劃失敗 ({e})，使用預設安全計畫")
            return [
                {"procedure_id": "open_file", "inputs": {"file_path": dynamic_params.get("file_path")}, "reason": "開啟檔案"},
                {"procedure_id": "add_text_to_end", "inputs": {"text": dynamic_params.get("text")}, "reason": "加入文字"},
                {"procedure_id": "save_file", "inputs": {}, "reason": "儲存"},
                {"procedure_id": "close_notepad", "inputs": {}, "reason": "關閉"},
                {"procedure_id": "handle_save_dialog", "inputs": {}, "reason": "處理可能的對話框"}
            ]

    def execute_task(self, task_description: str, dynamic_params: dict):
        plan = self._generate_plan(task_description, dynamic_params)
        print(f"\n[系統] 高階執行計畫已確定: {plan}")
        
        # 任務層級的全局狀態
        current_state = {
            "overall_status": "running",
            "current_procedure": None,
            "procedures_completed": [],
            "notepad_open": False,
            "current_file_path": None,
            "cursor_position": "unknown",
            "content_dirty": False,
            "save_dialog_visible": False
        }
        
        for step_idx, procedure in enumerate(plan):
            procedure_id = procedure.get("procedure_id")
            proc = self.kb.get_procedure(procedure_id)
            if not proc: continue
                
            print(f"\n{'=' * 70}")
            print(f"[系統] 進入 Procedure: 【{proc['name']}】")
            print(f"{'=' * 70}")
            
            current_state["current_procedure"] = proc['id']
            
            # Procedure 層級的狀態追蹤
            current_step_index = 0
            completed_steps = []
            failed_attempts = 0
            last_action_result = {"status": "尚未開始執行"}
            
            micro_step_count = 0 
            max_micro_steps = 10 # 增加微步上限，因為現在切成逐 step 執行 
            
            while micro_step_count < max_micro_steps:
                micro_step_count += 1
                image_b64, size = self.tools.capture_screen(current_step_index)
                
                decision = self._execute_step(
                    task_description, proc, dynamic_params, image_b64, 
                    current_step_index, completed_steps, failed_attempts, 
                    current_state, last_action_result
                )
                
                action = decision.get('action')
                print(f"  [思考] {decision.get('reasoning', '')}")
                print(f"  [決策] {action} (針對 step_id: {decision.get('step_id')})")
                
                # --- 新增的流程控制路由 ---
                if action == 'request_verification':
                    print(f"  → Agent 請求驗證 呼叫 verify_procedure()")
                    verify_result = self._verify_procedure(
                        task_description, proc, dynamic_params, image_b64,
                        current_step_index, completed_steps, failed_attempts,
                        current_state, last_action_result
                    )
                    
                    print(f"  [驗證] {verify_result.get('reasoning', '')}")
                    if verify_result.get('action') == 'advance_plan':
                        print(f"  ✓ Verifier 確認通過！")
                        current_state["procedures_completed"].append(proc['id'])
                        break
                    else:
                        print(f"  ✗ Verifier 判斷未完成，繼續執行")
                        last_action_result = {
                            "success": False,
                            "message": f"驗證未通過: {verify_result.get('reasoning', '')}"
                        }
                        failed_attempts += 1
                        continue
                elif action == 'advance_plan':
                    print(f"  ✓ Procedure【{proc['name']}】全部完成！")
                    current_state["procedures_completed"].append(proc['id'])
                    break 
                elif action == 'advance_step':
                    completed_steps.append(f"step_{current_step_index}")
                    current_step_index += 1
                    failed_attempts = 0 # 重置失敗次數
                    last_action_result = {"success": True, "message": f"成功推進到 step_{current_step_index}"}
                    print(f"  → 推進進度: 準備執行 step_{current_step_index}")
                    continue  
                elif action == 'need_recovery':
                    print("  ⚠ 偵測到畫面遮擋，執行緊急恢復 (按下 Enter 嘗試消除對話框)...")
                    self.tools.hotkey('enter')
                    last_action_result = {"success": False, "message": "已嘗試緊急恢復，請重新確認畫面"}
                    continue
                elif action == 'task_failed':
                    print(f"  ✗ Agent 宣告任務失敗。")
                    return False
                    
                # 執行標準動作
                last_action_result = self._execute_action(decision, size, dynamic_params)
                
                if not last_action_result.get('success'):
                    failed_attempts += 1
                    
                time.sleep(1) # 動作後等待畫面更新

                
            if micro_step_count >= max_micro_steps:
                print(f"  ⚠ 在【{proc['name']}】卡住超過 {max_micro_steps} 次，強制進入下一階段。")

        print("\n🎉 整個規劃已全部執行完畢！")
        return True
        
    # def _make_vision_decision(self, task: str, proc: dict, dynamic_params: dict, 
    #                           image_b64: str, current_step_index: int, 
    #                           completed_steps: list, failed_attempts: int, 
    #                           current_state: dict, last_action_result: dict):
                              
    #     suggested_steps = json.dumps(proc['steps'], ensure_ascii=False, indent=2)
    #     for key, val in dynamic_params.items():
    #         suggested_steps = suggested_steps.replace(f"{{{key}}}", str(val))
        
    #     total_steps = len(proc['steps'])
    #     is_executing = current_step_index < total_steps

    #     if is_executing:
    #         # 【執行階段】：沒收 advance_plan，強制它只能做事或推進單一步驟
    #         current_step_info = json.dumps(proc['steps'][current_step_index], ensure_ascii=False, indent=2)
    #         phase_instruction = f"""
    #         【目前狀態：執行步驟中 (進度: 第 {current_step_index + 1}/{total_steps} 步)】
    #         你的唯一任務是執行這一個步驟：
    #         {current_step_info}

    #         警告：因為步驟尚未全部執行完畢，你【絕對不可以】回傳 advance_plan！
    #         如果你認為這個步驟已經達成，請回傳 advance_step 進入下一步。
    #         """
    #         available_actions = """
    #         - click_by_image
    #         - click_by_coordinates
    #         - check_element_exists
    #         - type_text
    #         - press_key
    #         - hotkey
    #         - open_program
    #         - wait
    #         - advance_step
    #         - need_recovery
    #         """
    #     else:
    #         # 【驗證階段】：沒收所有操作工具，強制它只能檢查畫面
    #         phase_instruction = f"""
    #         【目前狀態：所有步驟已執行完畢，進入驗證階段】
    #         你的唯一任務是：檢查目前的螢幕截圖，是否完全符合以下 success_checks：
    #         {json.dumps(proc.get("success_checks", []), ensure_ascii=False, indent=2)}

    #         如果畫面完全符合成功標準，請回傳 advance_plan。
    #         如果畫面不符合（例如還停留在錯誤畫面，或者沒有發生預期變化），請回傳 need_recovery。
    #         """
    #         available_actions = """
    #         - advance_plan
    #         - need_recovery
    #         - task_failed
    #         """

    #     prompt = f"""
    #                 你是本地端電腦操作 Agent 的 Procedure Step Executor。

    #                 你不是 Planner。
    #                 你不能自由重新規劃任務。
    #                 你只能根據目前 procedure 的 steps，決定下一個要執行的低階 action。

    #                 目前使用者任務：
    #                 {task}

    #                 目前 procedure：
    #                 {proc["id"]} - {proc["name"]}

    #                 procedure 目標：
    #                 {proc.get("goal", "")}

    #                 {phase_instruction}

    #                 procedure steps：
    #                 {suggested_steps}

    #                 目前 procedure 的執行進度：
    #                 - current_step_index: {current_step_index}
    #                 - completed_steps: {completed_steps}
    #                 - failed_attempts: {failed_attempts}

    #                 目前任務狀態：
    #                 {json.dumps(current_state, ensure_ascii=False)}

    #                 上一個 action 的執行結果：
    #                 {json.dumps(last_action_result, ensure_ascii=False)}

    #                 你現在看到的是螢幕截圖。

    #                 你的工作：
    #                 1. 判斷目前畫面是否符合 current_step 的執行條件。
    #                 2. 如果 current_step 尚未完成，請執行 current_step 指定的 action。
    #                 3. 如果 current_step 已經完成，請回傳 advance_step。
    #                 4. 只有在 procedure 的所有 steps 都完成，而且 success_checks 也成立時，才可以回傳 advance_plan。
    #                 5. 如果畫面被儲存確認對話框擋住，且目前 procedure 不是 handle_save_dialog，請回傳 need_recovery。
    #                 6. 不要重複執行已完成的 step。
    #                 7. 不要自己發明 procedure 或 action。
    #                 8. 不要因為「看起來差不多」就提早 advance_plan。

    #                 可用 action：
    #                 - click_by_image
    #                 - click_by_coordinates
    #                 - check_element_exists
    #                 - type_text
    #                 - press_key
    #                 - hotkey
    #                 - open_program
    #                 - wait
    #                 - advance_step
    #                 - advance_plan
    #                 - need_recovery
    #                 - task_failed

    #                 圖片庫：
    #                 {self.image_lib.get_element_description()}

    #                 你現在看到的是螢幕截圖。

    #                 請仔細核對以下成功標準 (success_checks)：
    #                 {json.dumps(proc.get("success_checks", []), ensure_ascii=False, indent=2)}

    #                 如果你發現畫面已經完全符合上述標準（例如：字已經打上去了、檔案已經存了），你 **絕對不可以** 再做任何多餘的操作！
    #                 你必須立刻輸出 "action": "advance_plan"。並直接前往下一個步驟或 procedure。
    #                 不要因為「看起來還能做什麼」就繼續動作。

    #                 請只輸出 JSON，不要輸出其他文字。

    #                 輸出格式：
    #                 {{
    #                 "screen_observation": "我現在畫面上看到了什麼",
    #                 "are_success_checks_met": true 或 false,
    #                 "reasoning": "根據畫面與目前 step，我判斷...",
    #                 "action": "動作名稱",
    #                 "step_id": "目前要執行或完成的 step_id",
    #                 "element_name": null,
    #                 "x": null,
    #                 "y": null,
    #                 "text": null,
    #                 "key": null,
    #                 "keys": null,
    #                 "program": null,
    #                 "seconds": null,
    #                 "confidence": 0.0,
    #                 "expected_result": "執行後應該看到或發生什麼"
    #                 }}
    #                 """
    #     response = ollama.chat(
    #         model=VISION_MODEL,
    #         messages=[{
    #             'role': 'user',
    #             'content': prompt,
    #             'images': [image_b64]
    #         }],
    #         format='json',
    #         options={'temperature': 0.1, 'num_predict': 500}
    #     )
        
    #     try:
    #         return json.loads(response['message']['content'])
    #     except json.JSONDecodeError:
    #         return {'action': 'wait', 'seconds': 1, 'reasoning': 'JSON解析失敗，等待重試'}

    def _execute_step(self, task: str, proc: dict, dynamic_params: dict, 
                              image_b64: str, current_step_index: int, 
                              completed_steps: list, failed_attempts: int, 
                              current_state: dict, last_action_result: dict):
                              
        suggested_steps = json.dumps(proc['steps'], ensure_ascii=False, indent=2)
        for key, val in dynamic_params.items():
            suggested_steps = suggested_steps.replace(f"{{{key}}}", str(val))
        
        total_steps = len(proc['steps'])

        current_step_info = json.dumps(proc['steps'][current_step_index], ensure_ascii=False, indent=2)
        phase_instruction = f"""
        【目前狀態：執行步驟中 (進度: 第 {current_step_index + 1}/{total_steps} 步)】
        你的唯一任務是執行這一個步驟：
        {current_step_info}

        警告：因為步驟尚未全部執行完畢，你【絕對不可以】回傳 request_verification
        如果你認為這個步驟已經達成，請回傳 request_verification 進入下一步。
        """
        available_actions = """
        - click_by_image
        - click_by_coordinates
        - check_element_exists
        - type_text
        - press_key
        - hotkey
        - open_program
        - wait
        - request_verification
        - need_recovery
        """

        prompt = f"""
                    你是本地端電腦操作 Agent 的 Procedure Step Executor。

                    你不是 Planner。
                    你不能自由重新規劃任務。
                    你只能根據目前 procedure 的 steps，決定下一個要執行的低階 action。

                    目前使用者任務：
                    {task}

                    目前 procedure：
                    {proc["id"]} - {proc["name"]}

                    {phase_instruction}

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

                    可用action：
                    {available_actions}

                    圖片元件：
                    {self.image_lib.get_element_description()}

                    你現在看到的是螢幕截圖。

                    規則：
                    1. 如果目前 step 尚未完成，請執行目前 step 指定的 action。
                    2. 如果目前 step 已經完成，請回傳 request_verification。
                    3. 不可以回傳 advance_plan。
                    4. 不可以執行不是目前 step 指定的 action。
                    5. 不可以重複執行已完成的 step。
                    6. 不可以自己發明 action。
                    7. 如果畫面被儲存確認對話框或其他彈窗擋住，回傳 need_recovery。

                    請只輸出 JSON，不要輸出其他文字。

                    輸出格式：
                    格式：
                    {{
                    "action": "動作名稱",
                    "step_id": "目前 step_id",
                    "args": {{}},
                    "reason": "簡短原因"
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
        
    def _verify_procedure(self, task: str, proc: dict, dynamic_params: dict, 
                              image_b64: str, current_step_index: int, 
                              completed_steps: list, failed_attempts: int, 
                              current_state: dict, last_action_result: dict):
                              
        suggested_steps = json.dumps(proc['steps'], ensure_ascii=False, indent=2)
        for key, val in dynamic_params.items():
            suggested_steps = suggested_steps.replace(f"{{{key}}}", str(val))

        phase_instruction = f"""
        【目前狀態：所有步驟已執行完畢，進入驗證階段】
        你的唯一任務是：檢查目前的螢幕截圖，是否完全符合以下 success_checks：
        {json.dumps(proc.get("success_checks", []), ensure_ascii=False, indent=2)}

        如果畫面完全符合成功標準，請回傳 advance_plan。
        如果畫面不符合（例如還停留在錯誤畫面，或者沒有發生預期變化），請回傳 need_recovery。
        """
        available_actions = """
        - advance_plan
        - need_recovery
        - task_failed
        """

        prompt = f"""
                    你是本地端電腦操作 Agent 的 Procedure Verifier。

                    你不是 Executor，不能執行滑鼠、鍵盤、輸入文字或開啟程式。
                    你只能根據目前螢幕截圖，判斷這個 procedure 是否完成。

                    目前使用者任務：
                    {task}

                    目前 procedure：
                    {proc["id"]} - {proc["name"]}

                    procedure 目標：
                    {proc.get("goal", "")}

                    目前任務狀態：
                    {json.dumps(current_state, ensure_ascii=False)}

                    上一個 action 的執行結果：
                    {json.dumps(last_action_result, ensure_ascii=False)}

                    可用action：
                    {available_actions}

                    你現在看到的是螢幕截圖。

                    判斷規則：
                    1. 如果成功標準全部符合，回傳 advance_plan。
                    2. 如果只有部分不符合，但看起來可以修復，回傳 need_recovery。
                    3. 如果畫面狀態明顯錯誤且無法繼續，回傳 task_failed。
                    4. 不可以回傳 hotkey、type_text、click_by_image、open_program 等低階 action。
                    5. 不可以因為「大概完成」就回傳 advance_plan，必須符合成功標準。

                    {phase_instruction}

                    如果你發現畫面已經完全符合上述標準（例如：字已經打上去了、檔案已經存了），你 **絕對不可以** 再做任何多餘的操作！
                    你必須立刻輸出 "action": "advance_plan"。並直接前往下一個步驟或 procedure。
                    不要因為「看起來還能做什麼」就繼續動作。

                    請只輸出 JSON，不要輸出其他文字。

                    輸出格式：
                    {{
                    "action": "advance_plan 或 need_recovery 或 task_failed",
                    "checks_met": true,
                    "failed_check": null,
                    "reason": "簡短說明"
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
        action = decision.get('action')
        try:
            if action == 'click_by_image':
                return self.tools.click_by_image(decision.get('element_name'))
            elif action == 'click_by_coordinates':
                return self.tools.click_by_coordinates(decision.get('x',0), decision.get('y',0), screen_size)
            elif action == 'check_element_exists':
                return self.tools.check_element_exists(decision.get('element_name'))
            elif action == 'type_text':
                text_to_type = decision.get('text', dynamic_params.get('text'))
                if not text_to_type or '{text}' in text_to_type: text_to_type = dynamic_params.get('text')
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
            else:
                return {'success': False, 'message': f"無效的動作: {action}"}
        except Exception as e:
            return {'success': False, 'message': f"執行發生例外: {e}"}

if __name__ == "__main__":
    agent = VisionGuidedAgent()
    
    task = "請用點擊的方式打開桌面上的 test.txt，在最後面加上『AI 自動化執行測試』，儲存並關閉視窗。"
    
    params = {
        "file_path": "C:\\Users\\luhon\\Desktop\\test.txt", 
        "text": f"AI 自動化執行測試 - 時間: {time.strftime('%H:%M:%S')}"
    }
    
    print("將在 3 秒後開始執行任務...")
    time.sleep(3)
    
    agent.execute_task(task, params)