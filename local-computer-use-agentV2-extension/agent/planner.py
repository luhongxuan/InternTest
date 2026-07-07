"""Planner：只觀察、只規劃、不操作。

流程：截圖 -> 呼叫模型 -> 解析/驗證計畫 JSON -> 疊加關鍵字安全掃描 -> 回傳計畫。
"""

from typing import Dict, Optional, Tuple

from . import prompts, safety, schemas


class Planner:
    def __init__(self, client, screen_manager, model: str, logger):
        self.client = client
        self.screen = screen_manager
        self.model = model
        self.logger = logger

    def make_plan(self, task: str, revise_note: Optional[str] = None) -> Tuple[Optional[Dict], str]:
        """回傳 (plan 或 None, 訊息)。"""
        shot = self.screen.capture(tag="planning")
        task_text = task if not revise_note else f"{task}\n\n[使用者修改意見] {revise_note}"

        system = prompts.PLANNING_SYSTEM
        user = prompts.build_planning_user(task_text)
        parsed, raw = self.client.chat_json(self.model, system, user, image_b64=shot["image_b64"])

        self.logger.log("planning_model_response",
                        screenshot=shot["path"], raw=raw[:2000],
                        parsed_ok=parsed is not None)

        if parsed is None:
            return None, "Planner 回傳的內容無法解析為 JSON"

        ok, err, plan = schemas.validate_plan(parsed)
        if not ok:
            return None, f"計畫格式不合法：{err}"

        # 疊加關鍵字安全掃描：模型說安全不代表真的安全。
        kw = safety.scan_task_risk(task_text, plan)
        if not kw["is_safe"]:
            plan["safety_check"]["is_safe"] = False
            plan["safety_check"]["risk_level"] = "high"
            plan["safety_check"]["reason"] = (
                plan["safety_check"]["reason"] + f" | 系統掃描：{kw['reason']}"
            ).strip(" |")

        plan["_screenshot_path"] = shot["path"]  # 供前端顯示 Planner 看到的畫面
        self.logger.log("plan_created",
                        task_summary=plan["task_summary"],
                        safety=plan["safety_check"],
                        steps=len(plan["plan"]))
        return plan, "ok"
