import os
from pathlib import Path

# 目標資料夾
TARGET_DIR = "v5build-cdp_copy"
# 需要被偽裝的副檔名
DANGEROUS_EXTS = ['.py', '.js', '.json', '.html', '.css']

def mask_extensions():
    target_path = Path(TARGET_DIR)
    
    # 走訪資料夾內所有檔案
    for file_path in target_path.rglob("*"):
        if file_path.is_file():
            # 檢查副檔名是否在危險清單中
            if file_path.suffix in DANGEROUS_EXTS:
                # 加上 .txt 偽裝
                new_path = file_path.with_name(file_path.name + ".txt")
                file_path.rename(new_path)
                print(f"已偽裝: {file_path.name} -> {new_path.name}")

if __name__ == "__main__":
    mask_extensions()