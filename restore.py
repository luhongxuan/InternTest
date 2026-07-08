import os
from pathlib import Path

TARGET_DIR = "agentControllV3"

def unmask_extensions():
    target_path = Path(TARGET_DIR)
    
    for file_path in target_path.rglob("*.txt"):
        if file_path.is_file():
            # 檢查原本的副檔名是不是我們偽裝的
            original_name = file_path.name[:-4] # 移除最後的 .txt
            if any(original_name.endswith(ext) for ext in ['.py', '.js', '.json', '.html', '.css']):
                new_path = file_path.with_name(original_name)
                file_path.rename(new_path)
                print(f"已還原: {file_path.name} -> {new_path.name}")

if __name__ == "__main__":
    unmask_extensions()