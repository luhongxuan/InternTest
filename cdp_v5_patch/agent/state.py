"""任務狀態機。集中定義狀態與合法轉換，方便除錯與展示。"""

from enum import Enum


class TaskState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_USER_APPROVAL = "awaiting_user_approval"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 合法轉換表：只做基本檢查，避免程式亂跳狀態。
_LEGAL = {
    TaskState.IDLE: {TaskState.PLANNING, TaskState.CANCELLED},
    TaskState.PLANNING: {TaskState.AWAITING_USER_APPROVAL, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.AWAITING_USER_APPROVAL: {TaskState.EXECUTING, TaskState.PLANNING, TaskState.CANCELLED},
    TaskState.EXECUTING: {TaskState.PAUSED, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.PAUSED: {TaskState.EXECUTING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


def can_transition(src: TaskState, dst: TaskState) -> bool:
    return dst in _LEGAL.get(src, set())
