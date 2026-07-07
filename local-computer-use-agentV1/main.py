"""CLI 入口。

流程：輸入任務 -> Planner 產生計畫 -> 顯示計畫與安全檢查 ->
使用者 A/R/C -> approve 才進 Execution -> 顯示結果。
"""

import argparse
import json
import sys

import config
from agent.agent_loop import AgentLoop
from agent.logger import RunLogger, info, warn
from agent.model_client import OllamaClient
from agent.planner import Planner
from agent.screen import ScreenManager
from agent.state import TaskState
from agent.tools import ToolExecutor


def print_plan(plan: dict) -> None:
    sc = plan["safety_check"]
    print("\n" + "=" * 56)
    print(f"任務摘要：{plan['task_summary']}")
    print(f"安全檢查：is_safe={sc['is_safe']} risk={sc['risk_level']}")
    print(f"          {sc['reason']}")
    print("-" * 56)
    print("計畫步驟：")
    for s in plan["plan"]:
        print(f"  {s['step']}. {s['goal']}  ({s['expected_action_type']})")
    print("=" * 56)
    print(plan.get("question_to_user", ""))


def ask_confirm(message: str) -> bool:
    """執行階段遇到高風險動作時，問使用者 y/n。"""
    print(f"\n[需要確認] {message}")
    ans = input("是否允許此動作？(y/N) ").strip().lower()
    return ans == "y"


def main() -> int:
    parser = argparse.ArgumentParser(description="本地端通用 Computer Use Agent (MVP)")
    parser.add_argument("--task", type=str, help="自然語言任務。省略則互動輸入。")
    parser.add_argument("--max-steps", type=int, default=config.MAX_STEPS)
    args = parser.parse_args()
    config.MAX_STEPS = args.max_steps

    logger = RunLogger(config.LOG_DIR)
    print("本地端通用 Computer Use Agent — MVP")
    print("提醒：執行期間把滑鼠移到螢幕左上角可緊急中止（FAILSAFE）。\n")

    task = args.task or input("請輸入任務：").strip()
    if not task:
        warn("任務為空，結束。")
        return 1
    logger.log("task_received", task=task, max_steps=config.MAX_STEPS)

    try:
        screen = ScreenManager(config.MONITOR_INDEX, config.MODEL_MAX_WIDTH, config.SCREENSHOT_DIR)
    except Exception as e:
        warn(f"初始化螢幕失敗：{e}")
        return 1
    info(f"目標螢幕真實尺寸 {screen.real_size}，offset {screen.offset}")

    client = OllamaClient(config.OLLAMA_HOST, config.REQUEST_TIMEOUT, config.MODEL_TEMPERATURE)
    planner = Planner(client, screen, config.PLANNER_MODEL, logger)

    # --- Planning + 使用者確認迴圈 ---
    revise_note = None
    plan = None
    while True:
        print("\n[planning] 產生計畫中...")
        plan, msg = planner.make_plan(task, revise_note)
        if plan is None:
            warn(f"規劃失敗：{msg}")
            retry = input("重試規劃？(y/N) ").strip().lower()
            if retry == "y":
                continue
            logger.log("planning_aborted", reason=msg)
            return 1

        print_plan(plan)
        if not plan["safety_check"]["is_safe"]:
            warn("此任務被判定為高風險，請特別謹慎。")

        choice = input("\n[A] Approve並執行  [R] 修改計畫  [C] 取消： ").strip().upper()
        if choice == "A":
            logger.log("plan_approved", plan=plan)
            break
        elif choice == "R":
            revise_note = input("請輸入修改意見：").strip()
            logger.log("plan_revise", note=revise_note)
            continue
        else:
            logger.log("plan_cancelled")
            info("任務已取消。")
            return 0

    # --- Execution ---
    tools = ToolExecutor(screen, config.ACTION_DELAY)
    loop = AgentLoop(client, screen, tools, config.EXECUTOR_MODEL, logger, config, ask_confirm)

    print("\n[executing] 開始執行。Ctrl+C 或滑鼠移到左上角可中止。")
    try:
        result = loop.run(task, plan)
    except KeyboardInterrupt:
        loop.state = TaskState.CANCELLED
        logger.log("user_interrupt")
        print("\n[cancelled] 使用者中止。")
        logger.close()
        return 0

    print("\n" + "#" * 56)
    print(f"最終狀態：{result.state.value}")
    print(f"步數：{result.steps}")
    print(f"說明：{result.reason}")
    print(f"Log：{logger.path}")
    print("#" * 56)
    logger.log("run_end", state=result.state.value, steps=result.steps, reason=result.reason)
    logger.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
