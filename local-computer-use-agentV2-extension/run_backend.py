"""啟動後端：python run_backend.py"""

import uvicorn

import config

if __name__ == "__main__":
    print(f"啟動後端 http://{config.BACKEND_HOST}:{config.BACKEND_PORT}")
    print("提醒：執行任務時滑鼠移到螢幕左上角可緊急中止（FAILSAFE）。")
    uvicorn.run("backend.server:app", host=config.BACKEND_HOST,
                port=config.BACKEND_PORT, reload=False)
