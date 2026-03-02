"""Task lifecycle state machine for v2 tasks."""

from models import TaskStatus

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.INBOX: {TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.PENDING: {TaskStatus.EXECUTING, TaskStatus.CANCELLED},
    TaskStatus.EXECUTING: {TaskStatus.REVIEW, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED},
    TaskStatus.REVIEW: {TaskStatus.MERGING, TaskStatus.REJECTED, TaskStatus.CANCELLED},
    TaskStatus.MERGING: {TaskStatus.COMPLETE, TaskStatus.CONFLICT},
    TaskStatus.CONFLICT: {TaskStatus.MERGING, TaskStatus.CANCELLED},
    TaskStatus.REJECTED: {TaskStatus.PENDING},
    TaskStatus.FAILED: {TaskStatus.PENDING},
    TaskStatus.TIMEOUT: {TaskStatus.PENDING},
    TaskStatus.COMPLETE: set(),
    TaskStatus.CANCELLED: set(),
}

TERMINAL_STATES = {TaskStatus.COMPLETE, TaskStatus.CANCELLED}


def can_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """Check if a transition is allowed."""
    return to_status in VALID_TRANSITIONS.get(from_status, set())


def validate_transition(from_status: TaskStatus, to_status: TaskStatus) -> None:
    """Raise ValueError if the transition is invalid."""
    if not can_transition(from_status, to_status):
        raise ValueError(
            f"Invalid task transition: {from_status.value} -> {to_status.value}"
        )
