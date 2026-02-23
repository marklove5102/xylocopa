"""Task Dispatcher — core scheduling loop for CC workers."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from config import MAX_CONCURRENT_WORKERS, MAX_RETRIES
from database import SessionLocal
from models import Project, Task, TaskStatus
from worker_manager import WorkerManager

logger = logging.getLogger("orchestrator.dispatcher")


def _utcnow():
    return datetime.now(timezone.utc)


class TaskDispatcher:
    """Main scheduling loop: harvest results, detect timeouts, assign tasks."""

    def __init__(self, worker_manager: WorkerManager):
        self.worker_mgr = worker_manager
        self.running = False

    async def run(self):
        """Start the dispatcher loop."""
        self.running = True
        logger.info("Dispatcher started (max_workers=%d)", MAX_CONCURRENT_WORKERS)

        # Recover any tasks left in EXECUTING from a previous crash
        self._recover_stale_tasks()

        while self.running:
            try:
                db = SessionLocal()
                try:
                    self._tick(db)
                finally:
                    db.close()
            except Exception:
                logger.exception("Dispatcher tick failed")
            await asyncio.sleep(2)

        logger.info("Dispatcher stopped")

    def stop(self):
        """Signal the dispatcher to stop."""
        self.running = False

    def _tick(self, db: Session):
        """Single iteration of the dispatch loop."""
        # 1. Harvest completed workers
        self._harvest_completed(db)

        # 2. Timeout detection
        self._check_timeouts(db)

        # 3. Auto-retry failed tasks
        self._auto_retry(db)

        # 4. Assign new tasks to workers
        self._assign_tasks(db)

        db.commit()

    # ---- Step 1: Harvest ----

    def _harvest_completed(self, db: Session):
        """Check executing tasks whose containers have exited."""
        executing = (
            db.query(Task)
            .filter(Task.status == TaskStatus.EXECUTING)
            .filter(Task.container_id.is_not(None))
            .all()
        )
        for task in executing:
            status = self.worker_mgr.get_status(task.container_id)
            if status not in ("exited", "removed"):
                continue

            # Read logs before cleanup
            logs = self.worker_mgr.get_logs(task.container_id)
            task.stream_log = _truncate(logs, 50000)
            task.completed_at = _utcnow()

            if "EXIT_SUCCESS" in logs:
                task.status = TaskStatus.COMPLETED
                task.result_summary = _extract_summary(logs)
                logger.info("Task %s completed successfully", task.id)
            elif "EXIT_FAILURE" in logs:
                task.status = TaskStatus.FAILED
                task.error_message = _extract_error(logs)
                logger.warning("Task %s failed: %s", task.id, task.error_message)
            else:
                # Container exited without clear signal — treat as failure
                task.status = TaskStatus.FAILED
                task.error_message = "Worker exited without EXIT_SUCCESS or EXIT_FAILURE signal"
                logger.warning("Task %s: worker exited without status signal", task.id)

            # Clean up container
            if status != "removed":
                self.worker_mgr.stop_worker(task.container_id)

    # ---- Step 2: Timeouts ----

    def _check_timeouts(self, db: Session):
        """Kill workers that have exceeded their timeout."""
        executing = (
            db.query(Task)
            .filter(Task.status == TaskStatus.EXECUTING)
            .filter(Task.started_at.is_not(None))
            .all()
        )
        now = _utcnow()
        for task in executing:
            started = task.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (now - started).total_seconds()
            if elapsed > task.timeout_seconds:
                logger.warning(
                    "Task %s timed out after %ds (limit %ds)",
                    task.id, int(elapsed), task.timeout_seconds,
                )
                # Grab logs before killing
                if task.container_id:
                    task.stream_log = _truncate(
                        self.worker_mgr.get_logs(task.container_id), 50000
                    )
                    self.worker_mgr.stop_worker(task.container_id)
                task.status = TaskStatus.TIMEOUT
                task.error_message = f"Timed out after {int(elapsed)}s"
                task.completed_at = now

    # ---- Step 3: Auto-retry ----

    def _auto_retry(self, db: Session):
        """Re-queue failed/timed out tasks that haven't exceeded retry limit."""
        retriable = (
            db.query(Task)
            .filter(Task.status.in_([TaskStatus.FAILED, TaskStatus.TIMEOUT]))
            .filter(Task.retries < MAX_RETRIES)
            .all()
        )
        for task in retriable:
            task.retries += 1
            task.status = TaskStatus.PENDING
            task.container_id = None
            task.started_at = None
            task.completed_at = None
            prev_error = task.error_message or "unknown"
            task.error_message = None
            logger.info(
                "Task %s re-queued for retry #%d (was: %s)",
                task.id, task.retries, prev_error,
            )

    # ---- Step 4: Assign ----

    def _assign_tasks(self, db: Session):
        """Assign pending tasks to worker containers, respecting limits."""
        # Count currently executing tasks globally and per project
        executing = (
            db.query(Task)
            .filter(Task.status == TaskStatus.EXECUTING)
            .all()
        )
        total_active = len(executing)
        project_counts: dict[str, int] = {}
        for t in executing:
            project_counts[t.project] = project_counts.get(t.project, 0) + 1

        if total_active >= MAX_CONCURRENT_WORKERS:
            return

        # Get pending tasks ordered by priority then creation time
        pending = (
            db.query(Task)
            .filter(Task.status == TaskStatus.PENDING)
            .order_by(Task.priority.asc(), Task.created_at.asc())
            .all()
        )

        for task in pending:
            if total_active >= MAX_CONCURRENT_WORKERS:
                break

            # Check per-project concurrency limit
            project = db.get(Project, task.project)
            if not project:
                task.status = TaskStatus.FAILED
                task.error_message = f"Project '{task.project}' not found"
                continue

            proj_active = project_counts.get(task.project, 0)
            if proj_active >= project.max_concurrent:
                continue

            # Start worker
            try:
                container_id = self.worker_mgr.start_worker(task, project)
                task.container_id = container_id
                task.status = TaskStatus.EXECUTING
                task.started_at = _utcnow()
                total_active += 1
                project_counts[task.project] = proj_active + 1
                logger.info(
                    "Assigned task %s to worker (project: %s, active: %d/%d)",
                    task.id, task.project, total_active, MAX_CONCURRENT_WORKERS,
                )
            except Exception:
                logger.exception("Failed to start worker for task %s", task.id)
                task.status = TaskStatus.FAILED
                task.error_message = "Failed to start worker container"
                task.completed_at = _utcnow()

    # ---- Recovery ----

    def _recover_stale_tasks(self):
        """On startup, check for tasks stuck in EXECUTING from a previous crash."""
        db = SessionLocal()
        try:
            stale = (
                db.query(Task)
                .filter(Task.status == TaskStatus.EXECUTING)
                .all()
            )
            for task in stale:
                if task.container_id:
                    status = self.worker_mgr.get_status(task.container_id)
                    if status in ("removed", "exited"):
                        logs = self.worker_mgr.get_logs(task.container_id)
                        task.stream_log = _truncate(logs, 50000)
                        if status != "removed":
                            self.worker_mgr.stop_worker(task.container_id)

                task.status = TaskStatus.FAILED
                task.error_message = "Orchestrator restarted while task was executing"
                task.completed_at = _utcnow()
                logger.warning("Recovered stale task %s → FAILED", task.id)

            if stale:
                db.commit()
                logger.info("Recovered %d stale tasks", len(stale))
        finally:
            db.close()


# ---- Helpers ----

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... [truncated]"


def _extract_summary(logs: str) -> str:
    """Extract a brief summary from worker output."""
    lines = logs.strip().splitlines()
    # Look for EXIT_SUCCESS and grab context around it
    for i, line in enumerate(lines):
        if "EXIT_SUCCESS" in line:
            # Return last few lines before EXIT_SUCCESS as summary
            start = max(0, i - 5)
            return "\n".join(lines[start:i + 1])
    # Fallback: last 10 lines
    return "\n".join(lines[-10:])


def _extract_error(logs: str) -> str:
    """Extract error message from EXIT_FAILURE line."""
    for line in logs.strip().splitlines():
        if "EXIT_FAILURE" in line:
            # Format: EXIT_FAILURE: reason
            idx = line.find("EXIT_FAILURE:")
            if idx >= 0:
                return line[idx + len("EXIT_FAILURE:"):].strip()
            return line.strip()
    return "Unknown error (no EXIT_FAILURE found)"
