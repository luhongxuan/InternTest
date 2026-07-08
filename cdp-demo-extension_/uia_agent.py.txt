"""
UIA Desktop Agent - 最小可行原型
================================
展示 Hybrid 架構的第二層：用 Windows UI Automation 讀取元素 → LLM 決策 → 執行操作

使用方式：
  1. pip install pywinauto requests
  2. 確保 Ollama 正在運行，且有 qwen2.5:7b 模型
     ollama pull qwen2.5:7b
  3. 打開記事本（或任何你想操作的視窗）
  4. python uia_agent.py

它會：
  - 讀取目前最前面視窗的 UIA tree
  - 列出所有可互動元素
  - 問你想做什麼
  - 把元素列表 + 你的指令送給 LLM
  - LLM 選擇要操作的元素和動作
  - 執行操作
"""

import json
import time
import requests
from pywinauto import Desktop

# ============================================================
#  第一步：讀取 UIA Tree
# ============================================================

# 我們關心的控件類型（可互動的元素）
INTERACTIVE_TYPES = {
    "Button", "Edit", "MenuItem", "CheckBox", "RadioButton",
    "ComboBox", "ListItem", "TabItem", "Hyperlink",
    "TreeItem", "Slider", "MenuBar", "Menu",
    "Document",   # 例如記事本的編輯區
    "TextBox",    # 某些應用用這個
}

def get_active_window():
    """取得目前最前面的視窗"""
    desktop = Desktop(backend="uia")
    # 取得前景視窗
    from pywinauto import Application
    import ctypes
    
    # 用 Win32 API 取得前景視窗的 handle
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        print("❌ 找不到前景視窗")
        return None
    
    app = Application(backend="uia").connect(handle=hwnd)
    window = app.top_window()
    return window


def scan_elements(window, max_depth=5):
    """
    掃描視窗的 UIA tree，找出所有可互動元素
    回傳一個 list of dict，每個 dict 包含：
      - id: 流水號
      - type: 控件類型
      - name: 顯示名稱
      - bbox: [left, top, right, bottom] 精確座標
      - depth: 在樹中的深度（用於除錯）
    """
    elements = []
    element_id = 0

    def _walk(ctrl, depth=0):
        nonlocal element_id
        if depth > max_depth:
            return
        
        try:
            ctrl_type = ctrl.element_info.control_type or ""
            name = ctrl.element_info.name or ""
            
            # 只收集可互動的元素
            if ctrl_type in INTERACTIVE_TYPES:
                try:
                    rect = ctrl.rectangle()
                    # 過濾掉看不見的元素（寬或高為 0）
                    if rect.width() > 0 and rect.height() > 0:
                        elements.append({
                            "id": element_id,
                            "type": ctrl_type,
                            "name": name[:60],  # 截斷太長的名稱
                            "bbox": [rect.left, rect.top, rect.right, rect.bottom],
                            "depth": depth,
                            "_ctrl": ctrl,  # 保留原始控件引用，用於後續操作
                        })
                        element_id += 1
                except Exception:
                    pass
            
            # 遞迴掃描子元素
            for child in ctrl.children():
                _walk(child, depth + 1)
                
        except Exception:
            pass

    _walk(window.wrapper_object())
    return elements


def print_elements(elements):
    """格式化印出元素列表"""
    print(f"\n{'='*60}")
    print(f"  找到 {len(elements)} 個可互動元素")
    print(f"{'='*60}")
    print(f"  {'ID':>3}  {'類型':<14} {'名稱':<30} {'座標'}")
    print(f"  {'---':>3}  {'----':<14} {'----':<30} {'----'}")
    
    for el in elements:
        bbox = el['bbox']
        center_x = (bbox[0] + bbox[2]) // 2
        center_y = (bbox[1] + bbox[3]) // 2
        name_display = el['name'] if el['name'] else '(無名稱)'
        print(f"  {el['id']:>3}  {el['type']:<14} {name_display:<30} ({center_x}, {center_y})")
    
    print()


# ============================================================
#  第二步：送給 LLM 做決策
# ============================================================

def build_prompt(elements, user_task):
    """
    組裝 prompt：元素列表 + 使用者任務
    這就是 AI agent 實際送給 LLM 的東西（純文字，不需要截圖！）
    """
    # 把元素列表轉成 LLM 容易讀的格式
    el_list = []
    for el in elements:
        bbox = el['bbox']
        el_list.append({
            "id": el["id"],
            "type": el["type"],
            "name": el["name"],
            "center_x": (bbox[0] + bbox[2]) // 2,
            "center_y": (bbox[1] + bbox[3]) // 2,
        })

    prompt = f"""你是一個桌面自動化 agent。以下是目前視窗中所有可互動的 UI 元素：

{json.dumps(el_list, ensure_ascii=False, indent=2)}

使用者的任務是：{user_task}

請分析這些元素，選擇要操作的元素，然後回傳一個 JSON：
{{
  "element_id": <要操作的元素 id>,
  "action": "click" 或 "type",
  "text": "如果 action 是 type，要輸入的文字，否則為空字串",
  "reasoning": "你為什麼選這個元素（簡短說明）"
}}

只回傳 JSON，不要有其他文字。"""

    return prompt


def ask_llm(prompt, model="qwen2.5:7b"):
    """
    呼叫本地 Ollama API
    這一步就是整個 agent 的「大腦」
    """
    print("\n⏳ 正在等待 LLM 回應...")
    start = time.time()
    
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # 低溫度 = 更確定的輸出
                    "num_predict": 200,   # 不需要太長的回應
                }
            },
            timeout=60
        )
        resp.raise_for_status()
        result = resp.json()
        elapsed = time.time() - start
        
        raw = result.get("response", "")
        print(f"✅ LLM 回應完成（耗時 {elapsed:.1f} 秒）")
        print(f"📝 原始回應：{raw[:300]}")
        
        return raw
        
    except requests.exceptions.ConnectionError:
        print("❌ 無法連接 Ollama。請確認 Ollama 正在運行 (ollama serve)")
        return None
    except Exception as e:
        print(f"❌ LLM 呼叫失敗：{e}")
        return None


def parse_llm_response(raw_text):
    """解析 LLM 回傳的 JSON"""
    if not raw_text:
        return None
    
    # 嘗試找到 JSON 部分
    text = raw_text.strip()
    
    # 移除可能的 markdown 標記
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    # 嘗試找到 { } 區塊
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"⚠️ 無法解析 LLM 回應為 JSON")
        return None


# ============================================================
#  第三步：執行操作
# ============================================================

def execute_action(elements, decision):
    """
    根據 LLM 的決策執行操作
    這裡用的是 UIA 的精確座標，不是猜的！
    """
    element_id = decision.get("element_id")
    action = decision.get("action", "click")
    text = decision.get("text", "")
    reasoning = decision.get("reasoning", "")
    
    # 找到對應的元素
    target = None
    for el in elements:
        if el["id"] == element_id:
            target = el
            break
    
    if not target:
        print(f"❌ 找不到 element_id={element_id}")
        return False
    
    bbox = target["bbox"]
    center_x = (bbox[0] + bbox[2]) // 2
    center_y = (bbox[1] + bbox[3]) // 2
    ctrl = target["_ctrl"]
    
    print(f"\n{'='*60}")
    print(f"  🎯 執行操作")
    print(f"{'='*60}")
    print(f"  目標：{target['type']} \"{target['name']}\"")
    print(f"  座標：({center_x}, {center_y})  ← UIA 提供，精準度 100%")
    print(f"  動作：{action}")
    if text:
        print(f"  輸入：\"{text}\"")
    print(f"  理由：{reasoning}")
    print()
    
    # 詢問確認（安全機制）
    confirm = input("  按 Enter 執行，輸入 n 取消：").strip().lower()
    if confirm == "n":
        print("  ⏭️ 已取消")
        return False
    
    try:
        if action == "click":
            # 方法 1：優先用 UIA 原生操作（最精準）
            try:
                ctrl.click_input()
                print(f"  ✅ 已透過 UIA click_input() 點擊")
            except Exception:
                # 方法 2：fallback 到 pyautogui（座標點擊）
                import pyautogui
                pyautogui.click(center_x, center_y)
                print(f"  ✅ 已透過 pyautogui 點擊 ({center_x}, {center_y})")
                
        elif action == "type":
            # 先點擊聚焦
            try:
                ctrl.click_input()
            except Exception:
                import pyautogui
                pyautogui.click(center_x, center_y)
            
            time.sleep(0.3)
            
            # 輸入文字（用 pywinauto 的 type_keys 或直接設值）
            try:
                ctrl.type_keys(text, with_spaces=True, pause=0.05)
                print(f"  ✅ 已透過 UIA type_keys() 輸入文字")
            except Exception:
                # CJK 文字用剪貼簿方式輸入
                import pyperclip
                import pyautogui
                pyperclip.copy(text)
                pyautogui.hotkey('ctrl', 'v')
                print(f"  ✅ 已透過剪貼簿貼上文字")
        
        return True
        
    except Exception as e:
        print(f"  ❌ 執行失敗：{e}")
        return False


# ============================================================
#  主程式：互動式迴圈
# ============================================================

def main():
    print()
    print("╔══════════════════════════════════════════╗")
    print("║   UIA Desktop Agent - 最小可行原型       ║")
    print("║   Hybrid 架構第二層：UIA + LLM           ║")
    print("╚══════════════════════════════════════════╝")
    print()
    print("操作方式：")
    print("  1. 先把你要操作的視窗放到最前面")
    print("  2. 快速切回這個終端機")
    print("  3. 輸入你想做的事情")
    print("  4. 程式會自動掃描、分析、執行")
    print()
    print("輸入 quit 離開\n")

    while True:
        # --- 掃描前景視窗 ---
        input("👉 先把目標視窗放到最前面，然後按 Enter 掃描...")
        
        # 給使用者一點時間切換視窗
        print("   3 秒後掃描前景視窗...")
        time.sleep(3)
        
        window = get_active_window()
        if not window:
            continue
        
        try:
            title = window.window_text()
        except Exception:
            title = "(無法取得標題)"
        
        print(f"\n🪟 掃描到的視窗：「{title}」")
        
        # --- 掃描 UIA tree ---
        print("🔍 正在讀取 UIA tree...")
        start = time.time()
        elements = scan_elements(window)
        scan_time = time.time() - start
        print(f"   掃描耗時：{scan_time*1000:.0f} ms（截圖方案這一步要 3-10 秒）")
        
        if not elements:
            print("⚠️ 沒有找到可互動元素")
            continue
        
        # --- 顯示元素列表 ---
        print_elements(elements)
        
        # --- 詢問使用者任務 ---
        user_task = input("💬 你想做什麼？（例如：點擊檔案選單 / 在編輯區輸入 Hello）\n> ").strip()
        if user_task.lower() == "quit":
            print("👋 再見！")
            break
        if not user_task:
            continue
        
        # --- 送給 LLM ---
        prompt = build_prompt(elements, user_task)
        
        # 顯示 prompt 的 token 估算
        token_estimate = len(prompt) // 3  # 粗估
        print(f"\n📊 送給 LLM 的 prompt 大約 {token_estimate} tokens")
        print(f"   （同樣的任務用截圖方案要 2000-5000 tokens）")
        
        raw_response = ask_llm(prompt)
        decision = parse_llm_response(raw_response)
        
        if not decision:
            print("⚠️ LLM 沒有回傳有效的決策，請重試")
            continue
        
        # --- 執行操作 ---
        execute_action(elements, decision)
        
        print("\n" + "-"*40 + "\n")


# ============================================================
#  不用 LLM 的手動模式（用於測試 UIA 本身是否正常）
# ============================================================

def manual_mode():
    """
    不需要 Ollama，直接用鍵盤選擇元素來測試 UIA 是否正常運作
    python uia_agent.py --manual
    """
    print("\n🔧 手動模式（不需要 LLM）\n")
    
    input("👉 先把目標視窗放到最前面，然後按 Enter 掃描...")
    print("   3 秒後掃描...")
    time.sleep(3)
    
    window = get_active_window()
    if not window:
        return
    
    try:
        title = window.window_text()
    except Exception:
        title = "(無法取得標題)"
    
    print(f"\n🪟 視窗：「{title}」")
    
    elements = scan_elements(window)
    if not elements:
        print("⚠️ 沒有找到可互動元素")
        return
    
    print_elements(elements)
    
    while True:
        choice = input("輸入元素 ID 來點擊它（或 quit 離開）：").strip()
        if choice.lower() == "quit":
            break
        try:
            el_id = int(choice)
            target = next((el for el in elements if el["id"] == el_id), None)
            if target:
                print(f"  → 正在點擊 {target['type']} \"{target['name']}\"...")
                target["_ctrl"].click_input()
                print(f"  ✅ 完成")
            else:
                print(f"  ⚠️ 找不到 ID {el_id}")
        except ValueError:
            print("  ⚠️ 請輸入數字")


if __name__ == "__main__":
    import sys
    if "--manual" in sys.argv:
        manual_mode()
    else:
        main()