"""啟動後端伺服器。"""
import uvicorn
import config

if __name__ == "__main__":
    print(f"啟動後端 http://{config.BACKEND_HOST}:{config.BACKEND_PORT}")
    uvicorn.run(
        "backend.server:app",
        host=config.BACKEND_HOST,
        port=config.BACKEND_PORT,
        reload=False,
    )
