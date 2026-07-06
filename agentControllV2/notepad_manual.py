# notepad_manual.py
"""
記事本操作手冊 - Agent Procedure Manual

設計目的：
1. 這份檔案不是主程式，也不是固定流程。
2. 這份檔案提供 Agent 可選擇的 procedures。
3. Agent 必須根據使用者任務、目前畫面狀態、任務狀態，自己選擇要執行哪些 procedure。
4. 每個 procedure 都要明確描述：
   - 什麼時候可以用
   - 什麼時候不要用
   - 需要什麼輸入
   - 執行後會造成什麼狀態變化
   - 如何判斷成功或失敗
"""

# ------------------------------------------------------------
# Agent 使用規則
# ------------------------------------------------------------

AGENT_USAGE_RULES = {
    "planning_rules": [
        "只能從 NOTEPAD_PROCEDURES 裡選擇 procedure，不要自己發明不存在的 procedure。",
        "不要直接選擇低階 action，例如 hotkey、click、type_text；低階 action 只能出現在 procedure 的 steps 裡。",
        "每次選 procedure 前，先檢查 preconditions 是否符合。",
        "如果某個 procedure 已經成功執行，不要重複執行，除非 success_checks 顯示它失敗。",
        "如果 content_dirty 為 True，關閉記事本前必須先 save_file，或準備 handle_save_dialog。",
        "如果同一個 procedure 連續失敗 2 次，應該停止任務並回報 failed，不要無限重試。",
        "完成任務前，必須確認 final_success_criteria，而不是只根據模型直覺宣告完成。",
        "只能使用操作手冊中存在的 procedure id。",
        "不要自己發明 procedure id。",
        "如果任務要編輯檔案，通常需要 open_file。",
        "在執行 add_text_to_end 或任何輸入文字的操作之前，必須先執行 focus_notepad_editor 以確保游標在正確位置。",
        "如果任務要追加文字，通常需要 add_text_to_end。",
        "如果任務要求保留修改，必須包含 save_file。",
        "如果任務要求最後關閉視窗，必須包含 close_notepad。",
        "handle_save_dialog 只在「可能出現儲存確認對話框」時放在 close_notepad 後面。",
        "不要加入低階 action，例如 hotkey、press_key、type_text。",
        "不要重複同一個 procedure，除非它是 recovery 用途。"

    ],

    "state_fields": {
        "notepad_open": "記事本是否已開啟",
        "current_file_path": "目前記事本正在編輯的檔案路徑",
        "cursor_position": "游標位置，例如 unknown、end_of_file",
        "content_dirty": "目前內容是否有尚未儲存的變更",
        "save_dialog_visible": "是否出現『是否儲存變更』對話框",
        "last_successful_procedure": "上一個成功執行的 procedure",
        "failed_attempts": "每個 procedure 的失敗次數"
    }
}


# ------------------------------------------------------------
# 任務完成判斷範例
# ------------------------------------------------------------

TASK_SUCCESS_CRITERIA = {
    "append_text_and_close": [
        "目標檔案已經被開啟過",
        "指定文字已經被加入檔案內容",
        "檔案已經儲存",
        "記事本已經關閉",
        "沒有未處理的儲存確認對話框"
    ]
}


# ------------------------------------------------------------
# Procedures
# ------------------------------------------------------------

NOTEPAD_PROCEDURES = [
    {
        "id": "open_file",
        "name": "開啟指定文字檔",
        "goal": "使用記事本開啟指定的文字檔，讓後續 procedure 可以對該檔案進行編輯。",
        "intent_tags": [
            "open_text_file",
            "edit_text_file",
            "view_text_file",
            "start_notepad_task"
        ],

        "use_when": [
            "使用者任務需要查看、編輯或追加文字到某個文字檔。",
            "目前記事本尚未開啟。",
            "目前開啟的檔案不是目標檔案。"
        ],

        "do_not_use_when": [
            "目標檔案已經在記事本中開啟。",
            "目前有未儲存內容，且 current_file_path 不是目標檔案。",
            "不知道目標檔案路徑。"
        ],

        "required_inputs": {
            "file_path": {
                "type": "string",
                "description": "要開啟的文字檔完整路徑，例如 C:/Users/user/Desktop/test.txt",
                "required": True
            }
        },

        "preconditions": [
            "file_path is not empty",
            "file_path points to a .txt or text-editable file"
        ],

        "steps": [
            {
                "step_id": "open_with_notepad",
                "action": "open_program",
                "params_template": "notepad.exe {file_path}",
                "params_needed": ["file_path"],
                "description": "用記事本開啟指定檔案"
            },
            {
                "step_id": "wait_for_window",
                "action": "wait",
                "params": 2,
                "description": "等待記事本視窗開啟"
            }
        ],

        "state_updates_on_success": {
            "notepad_open": True,
            "current_file_path": "{file_path}",
            "cursor_position": "unknown",
            "content_dirty": False,
            "save_dialog_visible": False
        },

        "success_checks": [
            "記事本視窗存在",
            "目前畫面顯示記事本",
            "current_file_path 設定為目標 file_path"
        ],

        "failure_signals": [
            "等待後沒有出現記事本視窗",
            "系統跳出找不到檔案或權限錯誤",
            "開啟的是其他程式而不是記事本"
        ],

        "recovery_procedures": [
            "open_file"
        ],

        "recommended_next": [
            "add_text_to_end",
            "close_notepad"
        ],

        "risk_level": "low"
    },

    {
        "id": "add_text_to_end",
        "name": "在檔案末尾追加文字",
        "goal": "將指定文字加入目前記事本檔案的最後一行。",
        "intent_tags": [
            "append_text",
            "edit_text_file",
            "write_text",
            "add_log"
        ],

        "use_when": [
            "使用者任務要求新增、追加、寫入或記錄一段文字。",
            "記事本已經開啟。",
            "目標檔案已經是目前正在編輯的檔案。",
            "已經聚焦在記事本編輯區，或可以透過 focus_notepad_editor 聚焦。",
        ],

        "do_not_use_when": [
            "記事本尚未開啟。",
            "尚未指定要加入的文字。",
            "目前有儲存確認對話框擋住畫面。",
            "指定文字已經成功加入過，且沒有失敗證據。",
            "沒有聚焦在記事本編輯區，請透過 focus_notepad_editor 聚焦。"
        ],

        "required_inputs": {
            "text": {
                "type": "string",
                "description": "要加入檔案末尾的文字內容",
                "required": True
            }
        },

        "preconditions": [
            "notepad_open == True",
            "text is not empty",
            "save_dialog_visible == False"
        ],

        "steps": [
            {
                "step_id": "move_cursor_to_end",
                "action": "hotkey",
                "params": ["ctrl", "end"],
                "description": "將游標移到檔案最後"
            },
            {
                "step_id": "new_line",
                "action": "press_key",
                "params": "enter",
                "description": "新增一行，避免文字接在原本內容後面"
            },
            {
                "step_id": "type_text",
                "action": "type_text",
                "params_template": "{text}",
                "params_needed": ["text"],
                "description": "輸入指定文字"
            }
        ],

        "state_updates_on_success": {
            "cursor_position": "end_of_file",
            "content_dirty": True
        },

        "success_checks": [
            "畫面中可以看到剛剛輸入的文字，或文字輸入 action 回報成功",
            "content_dirty == True"
        ],

        "failure_signals": [
            "輸入後畫面沒有任何變化",
            "文字被輸入到錯誤位置",
            "輸入文字重複出現多次",
            "目前焦點不在記事本編輯區"
        ],

        "recovery_procedures": [
            "focus_notepad_editor",
            "add_text_to_end"
        ],

        "recommended_next": [
            "save_file"
        ],

        "risk_level": "medium"
    },

    {
        "id": "focus_notepad_editor",
        "name": "聚焦記事本編輯區",
        "goal": "確保鍵盤輸入會進入記事本的文字編輯區，而不是其他視窗或對話框。",
        "intent_tags": [
            "focus_window",
            "fix_typing_target",
            "recovery"
        ],

        "use_when": [
            "準備輸入文字前，但不確定目前焦點是否在記事本。",
            "剛才輸入文字失敗。",
            "畫面上記事本存在，但鍵盤輸入沒有反應。"
        ],

        "do_not_use_when": [
            "記事本尚未開啟。",
            "目前有儲存確認對話框需要先處理。"
        ],

        "required_inputs": {},

        "preconditions": [
            "notepad_open == True",
            "save_dialog_visible == False"
        ],

        "steps": [
            {
                "step_id": "click_editor_area",
                "action": "click_relative",
                "description": "請觀察螢幕截圖，自行找出記事本『白色空白文字編輯區』的精確位置，並在輸出的 JSON 中填入對應的 x 與 y 座標來點擊它。"
            },
            {
                "step_id": "wait_focus",
                "action": "wait",
                "params": 0.5,
                "description": "等待焦點切換"
            }
        ],

        "state_updates_on_success": {
            "notepad_open": True
        },

        "success_checks": [
            "記事本仍然是目前前景視窗",
            "沒有對話框遮住記事本",
            "畫面中編輯的區域有出現一條直直的游標，表示可以輸入文字",
        ],

        "failure_signals": [
            "點擊後前景視窗不是記事本",
            "畫面上找不到記事本"
        ],

        "recovery_procedures": [
            "open_file"
        ],

        "recommended_next": [
            "add_text_to_end",
            "save_file"
        ],

        "risk_level": "low"
    },

    {
        "id": "save_file",
        "name": "儲存目前檔案",
        "goal": "將記事本中尚未儲存的變更寫入目前檔案。",
        "intent_tags": [
            "save_file",
            "persist_changes",
            "finish_editing"
        ],

        "use_when": [
            "已經完成文字編輯，且需要保留變更。",
            "這個筆記的上方的分頁右邊有圓形的點點，表示有未儲存變更，這個是記事本中確認是否儲存最好的方法。",
            "content_dirty == True。",
            "關閉記事本前。"
        ],

        "do_not_use_when": [
            "記事本尚未開啟。",
            "目前沒有任何變更需要儲存。",
            "目前有儲存確認對話框，應該先使用 handle_save_dialog。"
        ],

        "required_inputs": {},

        "preconditions": [
            "notepad_open == True",
            "save_dialog_visible == False"
        ],

        "steps": [
            {
                "step_id": "press_ctrl_s",
                "action": "hotkey",
                "params": ["ctrl", "s"],
                "description": "使用 Ctrl+S 儲存目前檔案"
            },
            {
                "step_id": "wait_save",
                "action": "wait",
                "params": 1,
                "description": "等待儲存完成"
            }
        ],

        "state_updates_on_success": {
            "content_dirty": False
        },

        "success_checks": [
            "沒有出現另存新檔視窗",
            "沒有出現錯誤對話框",
            "content_dirty == False",
            "這個檔案的上方的分頁會從圓形的點點變成叉叉，表示已經儲存",
        ],

        "failure_signals": [
            "出現另存新檔視窗",
            "出現權限錯誤",
            "記事本上方分頁標籤文字旁邊的『圓形點點』依然存在，代表根本還沒存檔成功"
        ],

        "recovery_procedures": [
            "handle_save_dialog"
        ],

        "recommended_next": [
            "close_notepad"
        ],

        "risk_level": "low"
    },

    {
        "id": "close_notepad",
        "name": "關閉記事本",
        "goal": "關閉目前的記事本視窗。",
        "intent_tags": [
            "close_window",
            "finish_task",
            "close_notepad"
        ],

        "use_when": [
            "所有編輯與儲存工作都已完成。",
            "使用者任務要求關閉記事本。",
            "demo 流程進入最後階段。"
        ],

        "do_not_use_when": [
            "記事本尚未開啟。",
            "content_dirty == True 且尚未執行 save_file。",
            "目前有儲存確認對話框，應該先 handle_save_dialog。"
        ],

        "required_inputs": {},

        "preconditions": [
            "notepad_open == True",
            "save_dialog_visible == False"
        ],

        "steps": [
            {
                "step_id": "click_close_button",
                "action": "click_by_image",
                "params": "close_button",
                "description": "點擊記事本右上角關閉按鈕"
            },
            {
                "step_id": "wait_after_close",
                "action": "wait",
                "params": 1,
                "description": "等待視窗關閉或等待可能出現的儲存確認對話框"
            }
        ],

        "state_updates_on_success": {
            "notepad_open": False
        },

        "possible_state_updates": {
            "save_dialog_visible": True
        },

        "success_checks": [
            "記事本視窗消失",
            "或出現儲存確認對話框並等待後續處理",
            "畫面上沒有記事本的視窗出現並且回到桌面",
        ],

        "failure_signals": [
            "點擊關閉後記事本仍然存在",
            "找不到 close_button 圖片",
            "出現儲存確認對話框但沒有被處理"
        ],

        "recovery_procedures": [
            "handle_save_dialog",
            "close_notepad"
        ],

        "recommended_next": [
            "handle_save_dialog",
            "finish_task"
        ],

        "risk_level": "medium"
    },

    {
        "id": "handle_save_dialog",
        "name": "處理儲存確認對話框",
        "goal": "如果出現『是否儲存變更』對話框，就選擇儲存並關閉對話框；如果沒有出現，則不做任何破壞性操作。",
        "intent_tags": [
            "handle_dialog",
            "save_confirm",
            "recovery",
            "after_close"
        ],

        "use_when": [
            "關閉記事本後可能出現儲存確認對話框。",
            "儲存或關閉操作後，畫面疑似被對話框擋住。",
            "save_dialog_visible == True。"
        ],

        "do_not_use_when": [
            "確定沒有任何對話框。",
            "目前正在正常編輯文字，沒有彈窗。",
            "使用者明確要求不要儲存變更。"
        ],

        "required_inputs": {},

        "preconditions": [
            "notepad_open == True or save_dialog_visible == True"
        ],

        "steps": [
            {
                "step_id": "detect_save_dialog",
                "action": "check_element_exists",  # ← 改成 mainAgent.py 認得的
                "params": "save_confirm_dialog",
                "description": "檢查畫面上是否存在儲存確認對話框"
            },
            {
                "step_id": "confirm_save_if_dialog_exists",
                "action": "press_key",  # ← 改成基本的 press_key
                "params": "enter",
                "condition": "previous_step_found_dialog",  # 條件判斷移到 mainAgent 程式端處理
                "description": "如果儲存確認對話框存在,按 Enter 選擇儲存"
            },
            {
                "step_id": "wait_dialog_close",
                "action": "wait",
                "params": 1,
                "description": "等待對話框處理完成"
            }
        ],

        "state_updates_on_success": {
            "save_dialog_visible": False,
            "content_dirty": False
        },

        "success_checks": [
            "儲存確認對話框消失",
            "沒有其他錯誤對話框",
            "如果剛才是在關閉記事本，記事本應該也關閉"
        ],

        "failure_signals": [
            "按 Enter 後對話框仍然存在",
            "出現另存新檔或權限錯誤",
            "對話框偵測錯誤，按鍵送到錯誤視窗"
        ],

        "recovery_procedures": [
            "handle_save_dialog"
        ],

        "recommended_next": [
            "close_notepad",
            "finish_task"
        ],

        "risk_level": "medium"
    }
]