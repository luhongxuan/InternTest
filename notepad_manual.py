# notepad_manual.py
"""
記事本操作手冊 - 只有 procedures,沒有預設的執行順序
Agent 要自己決定用哪些、什麼順序
"""

NOTEPAD_PROCEDURES = [
    {
        "id": "open_file",
        "name": "開啟指定的檔案",
        "description": "用記事本開啟一個檔案",
        "when_to_use": "當需要編輯、查看某個文字檔案時,這通常是第一步",
        "prerequisites": "知道檔案的完整路徑",
        "steps": [
            {
                "action": "open_program",
                "params_template": "notepad.exe {file_path}",
                "params_needed": ["file_path"]
            },
            {
                "action": "wait",
                "params": 2
            }
        ],
        "after_this": "記事本會開啟,可以進行編輯操作"
    },
    {
        "id": "add_text_to_end",
        "name": "在檔案末尾加入文字",
        "description": "把游標移到檔案最後,加入新的一行文字",
        "when_to_use": "需要在檔案最後追加內容時",
        "prerequisites": "記事本已經開啟",
        "steps": [
            {"action": "hotkey", "params": ["ctrl", "end"]},
            {"action": "press_key", "params": "enter"},
            {
                "action": "type_text",
                "params_template": "{text}",
                "params_needed": ["text"]
            }
        ],
        "after_this": "檔案末尾多了新的一行,但還沒儲存"
    },
    {
        "id": "save_file",
        "name": "儲存目前檔案",
        "description": "把目前的變更寫入檔案",
        "when_to_use": "編輯完想保留變更時",
        "prerequisites": "記事本已經開啟且有變更",
        "steps": [
            {"action": "hotkey", "params": ["ctrl", "s"]},
            {"action": "wait", "params": 1}
        ],
        "after_this": "變更已寫入檔案,但如果是關閉時儲存,可能會有對話框"
    },
    {
        "id": "close_notepad",
        "name": "關閉記事本視窗",
        "description": "把記事本視窗關掉",
        "when_to_use": "所有編輯工作完成後",
        "prerequisites": "記事本開啟中",
        "steps": [
            {"action": "click_by_image", "params": "close_button"}
        ],
        "after_this": "如果檔案有未儲存變更,會跳出詢問是否儲存的對話框"
    },
    {
        "id": "handle_save_dialog",
        "name": "處理儲存確認對話框",
        "description": "檢查並處理『是否儲存變更』的對話框。如果對話框存在就按 Enter 儲存;不存在就跳過",
        "when_to_use": "剛執行完儲存或關閉操作後,可能會跳出這個對話框",
        "prerequisites": "無",
        "steps": [
            {
                "action": "check_and_handle_dialog",
                "params": "save_confirm_dialog"
            }
        ],
        "after_this": "如果有對話框就處理掉,沒有就什麼也不做"
    }
]