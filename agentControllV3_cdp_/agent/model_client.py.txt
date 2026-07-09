"""Ollama 模型呼叫封裝。

用 REST /api/chat，好處：
- format="json" 可強制模型輸出合法 JSON，大幅降低解析失敗率。
- 直接看得到 HTTP 內容，方便除錯。
- 圖片用 messages[].images 傳 base64。

對外只暴露 chat_json()，回傳 (parsed_dict_or_None, raw_text)。
"""

import json
from typing import Dict, List, Optional, Tuple

import requests


class OllamaClient:
    def __init__(self, host: str, timeout: int, temperature: float):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature

    def _post(self, messages: List[Dict], model: str) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",   # 強制 JSON 輸出
            "options": {"temperature": self.temperature},
        }
        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")

    def chat_json(
        self,
        model: str,
        system: str,
        user: str,
        image_b64: Optional[str] = None,
    ) -> Tuple[Optional[Dict], str]:
        """呼叫模型並嘗試解析 JSON。回傳 (dict 或 None, 原始文字)。"""
        user_msg: Dict = {"role": "user", "content": user}
        if image_b64:
            user_msg["images"] = [image_b64]
        messages = [{"role": "system", "content": system}, user_msg]

        try:
            raw = self._post(messages, model)
        except requests.RequestException as e:
            return None, f"[HTTP_ERROR] {e}"

        parsed = _safe_json_parse(raw)
        return parsed, raw


def _safe_json_parse(text: str) -> Optional[Dict]:
    """盡量從模型輸出中撈出 JSON 物件。
    先直接 parse；失敗再擷取第一個 { 到最後一個 } 的區段重試。
    """
    if not text:
        return None
    text = text.strip()
    # 去掉可能的 ```json 圍欄
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None
