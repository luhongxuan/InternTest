"""執行迴圈（CDP 版）：每一步用「元素清單 + 截圖」一起推論，用 CDP 點擊。

跟原本最大的差別：
1. 觀察來源從 mss 螢幕截圖換成 BrowserCDP.capture()（Page 截圖 + 可互動元素）。
2. 模型同時收到「截圖」和「元素清單文字」→ 輸出 click_element / type_in_element。
3. 單獨計時「模型推論」耗時（infer_sec），這才是你要量的重點。
"""

import time
from typing import Dict, List

import agentControllV3_cdp.agent.prompts as prompts
import agentControllV3_cdp.agent.schemas as schemas


class ExecutionResult:
    def __init__(self, reason: str, steps: int):
        self.reason = reason
        self.steps = steps


class AgentLoop:
    def __init__(self, client, browser, model, max_steps: int = 10):
        self.client = client
        self.browser = browser        # BrowserCDP
        self.model = model
        self.max_steps = max_steps
        self.history: List[Dict] = []

    def _history_text(self) -> str:
        lines = []
        for h in self.history[-5:]:
            a = h["action"]
            lines.append(f"- {a.get('action')} id={a.get('element_id','')} "
                         f"reason={str(a.get('reason',''))[:30]} "
                         f"result={'ok' if h['result'].get('ok') else 'fail'}")
        return "\n".join(lines)

    def run(self, task: str, plan_text: str = "") -> ExecutionResult:
        parse_fail = 0
        for step in range(1, self.max_steps + 1):
            # --- 觀察：截圖 + 元素清單 ---
            t0 = time.time()
            shot = self.browser.capture()
            observe_sec = time.time() - t0
            elements = shot["elements"]

            # --- 推論：截圖 + 元素清單一起餵給模型（單獨計時） ---
            user = prompts.build_execution_user(task, plan_text, self._history_text(), elements)
            t1 = time.time()
            parsed, raw = self.client.chat_json(
                self.model, prompts.EXECUTION_SYSTEM, user, image_b64=shot["image_base64"])
            infer_sec = time.time() - t1

            print(f"[step {step}] 元素 {len(elements)} 個 | 觀察 {observe_sec:.2f}s | "
                  f"模型推論 {infer_sec:.2f}s")
            print("  raw:", raw[:200])

            if parsed is None:
                parse_fail += 1
                if parse_fail >= 2:
                    return ExecutionResult("JSON 連續解析失敗", step)
                continue
            parse_fail = 0

            ok, err, action = schemas.validate_action(parsed)
            if not ok:
                print(f"  [!] 非法 action：{err}")
                self.history.append({"action": {"action": "invalid"}, "result": {"ok": False}})
                continue

            name = action["action"]
            print(f"  [action] {name} reason={action.get('reason','')[:40]}")

            if name == "finish_task":
                return ExecutionResult(action.get("reason", "任務完成"), step)
            if name == "fail_task":
                return ExecutionResult(action.get("reason", "模型放棄"), step)

            # --- 執行：CDP ---
            if name == "click_element":
                result = self.browser.click_element(elements, action["element_id"])
            elif name == "type_in_element":
                result = self.browser.type_in_element(elements, action["element_id"], action["text"])
            elif name == "scroll":
                result = {"ok": True, "noop": "scroll"}  # 需要的話再接 CDP wheel
            else:
                result = {"ok": False, "error": f"CDP 版未實作動作 {name}"}

            print(f"  [result] {'ok' if result.get('ok') else 'FAIL: ' + str(result.get('error'))}")
            self.history.append({"action": action, "result": result})
            time.sleep(0.3)

        return ExecutionResult("達到最大步數", self.max_steps)


if __name__ == "__main__":
    from model_client import OllamaClient
    from agentControllV3_cdp.agent.browser import BrowserCDP

    # 先用 Edge 開好 debugging port：
    #   msedge.exe --remote-debugging-port=9222 --user-data-dir=C:\edge-cdp
    client = OllamaClient(host="http://localhost:11434", timeout=180, temperature=0.2)
    browser = BrowserCDP(host="127.0.0.1", port=9222, model_max_width=1028)

    url, title = browser.get_url_title()
    print(f"目前分頁：{title} | {url}")

    loop = AgentLoop(client, browser, model="qwen2.5vl:7b", max_steps=5)
    result = loop.run("點擊登入按鈕")
    print("結束：", result.reason, "步數：", result.steps)
    browser.close()
