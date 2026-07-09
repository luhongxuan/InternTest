"""執行迴圈：使用者 approve 後才會進到這裡。
"""

import json
from typing import Callable, Dict, List, Optional

import prompts, schemas
import time


class ExecutionResult:
    def __init__(self, reason: str, steps: int):
        self.reason = reason
        self.steps = steps


class AgentLoop:
    def __init__(self, client, screen_manager, tool_executor, model):
        self.client = client
        self.screen = screen_manager
        self.tools = tool_executor
        self.model = model
        self.history: List[Dict] = []

    def _history_text(self) -> str:
        recent = self.history[-5:]  # 取最近 5 個步驟
        lines = []
        for h in recent:
            lines.append(f"- {h['action'].get('action')} "
                         f"reason={h['action'].get('reason','')[:40]} "
                         f"result={'ok' if h['result'].get('ok') else 'fail'}")
        return "\n".join(lines)

    def run(self, task: str) -> ExecutionResult:
        #guard = safety.LoopGuard(self.cfg.MAX_SAME_ACTION_REPEAT, self.cfg.MAX_NO_CHANGE)
        plan_text = task
        consecutive_parse_fail = 0
        start_time = time.time()
        for step in range(1, 2):
            time.sleep(2)

            shot = self.screen.capture_screen()

            # 呼叫模型
            mw, mh = shot["model_size"]
            user = prompts.build_execution_user(task, plan_text, self._history_text(), mw, mh)
            parsed, raw = self.client.chat_json(
                self.model, prompts.EXECUTION_SYSTEM, user, image_b64=shot["image_base64"])
            print(parsed, raw)
            # self.logger.log("model_response", step=step, screenshot=shot["path"],
            #                 state=self.state.value, screen_real=shot["real_size"],
            #                 screen_model=shot["model_size"], raw=raw[:2000],
            #                 parsed_ok=parsed is not None)
            if parsed is None:
                consecutive_parse_fail += 1
                print(f"[!] JSON 解析失敗（連續 {consecutive_parse_fail} 次）")
                if consecutive_parse_fail >= 2:
                    # self.logger.log("stop", step=step, reason="JSON 連續解析失敗")
                    return ExecutionResult("JSON 連續解析失敗")
                continue
            consecutive_parse_fail = 0

            # schema 驗證
            ok, err, action = schemas.validate_action(parsed)
            print(action)
            # self.logger.log("action_validation", step=step, ok=ok, error=err, action=action)
            print(f"[action] {action.get('action')} reason={action.get('reason','')[:40]}")
            # screenshot 動作：不需 OS 操作，直接進下一輪重新觀察
            if action["action"] == "screenshot":
                self.history.append({"action": action, "result": {"ok": True, "noop": "screenshot"}})
                continue

            # 實際執行
            result = self.tools.execute(action, shot["scale"])
            # self.logger.log("action_result", step=step, action=action, result=result)
            print(f"[result] {'ok' if result.get('ok') else 'FAIL: ' + str(result.get('error'))}")
            self.history.append({"action": action, "result": result})
        end_time = time.time()
        print(f"[loop] 耗時 {end_time - start_time:.2f} 秒")
        # self.logger.log("stop", reason=f"達到 max_steps={self.cfg.MAX_STEPS}")
        return ExecutionResult(f"達到最大步數", 1)

if __name__ == "__main__":
    from model_client import OllamaClient
    from screen import ScreenManager
    from tools import ToolExecutor

    client = OllamaClient(host="http://localhost:11434", timeout=180, temperature=0.2)
    screen = ScreenManager()
    tools = ToolExecutor(screen_manager=screen, action_delay=0.5)

    loop = AgentLoop(client, screen, tools, model="qwen2.5vl:7b")
    loop.run("幫我點擊登入按鈕")