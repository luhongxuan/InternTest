"""Logging：每步一行 JSONL，方便事後分析與展示；同時提供簡單 console 輸出。"""

import json
import os
import time
from typing import Any, Dict


class RunLogger:
    def __init__(self, log_dir: str):
        os.makedirs(log_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(log_dir, f"run_{ts}.jsonl")
        self._f = open(self.path, "a", encoding="utf-8")

    def log(self, event: str, **fields: Any) -> None:
        record: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
        }
        record.update(fields)
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass


# --- console 輔助（讓 CLI 好讀，不影響 JSONL 紀錄） ---

def info(msg: str) -> None:
    print(f"[i] {msg}")


def warn(msg: str) -> None:
    print(f"[!] {msg}")


def step_banner(n: int, state: str) -> None:
    print(f"\n===== Step {n} | state={state} =====")
