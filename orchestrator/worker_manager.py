"""Worker Manager — host subprocess lifecycle for CC workers and agents."""

import logging
import os
import shutil
import subprocess

from config import CLAUDE_BIN, PROJECTS_DIR
from models import Project

logger = logging.getLogger("orchestrator.worker")


class WorkerManager:
    """Manages CC worker subprocesses (ephemeral tasks and persistent agents)."""

    def __init__(self):
        self._verify_claude()

    def _verify_claude(self):
        """Check that the claude CLI is available."""
        try:
            result = subprocess.run(
                [CLAUDE_BIN, "--version"],
                capture_output=True, text=True, timeout=10,
                env=self._clean_env(),
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                logger.info("Claude CLI found: %s", version)
            else:
                logger.warning("Claude CLI returned non-zero: %s", result.stderr.strip())
        except FileNotFoundError:
            logger.warning(
                "Claude CLI '%s' not found — install it or set CLAUDE_BIN",
                CLAUDE_BIN,
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("Failed to verify claude CLI: %s", e)

    @staticmethod
    def _clean_env() -> dict[str, str]:
        """Return os.environ without CLAUDECODE vars so spawned claude
        processes don't think they're nested inside another session.
        Sets XYLOCOPA_MANAGED=1 (and legacy AGENTHIVE_MANAGED=1) for general
        orchestrator context.
        Note: process distinction uses -p flag check, not this env var."""
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        env["XYLOCOPA_MANAGED"] = "1"
        env["AGENTHIVE_MANAGED"] = "1"  # legacy alias
        return env

    @staticmethod
    def _default_project_path(project_name: str) -> str:
        """Return the default path for a new project directory (clone/init only)."""
        if PROJECTS_DIR:
            return os.path.join(PROJECTS_DIR, project_name)
        return os.path.join("/projects", project_name)

    # =====================================================================
    # Project setup
    # =====================================================================

    def ensure_project_ready(self, project: Project) -> str:
        """Validate project directory exists. Returns the project path."""
        project_path = project.path
        if not os.path.isdir(project_path):
            raise FileNotFoundError(f"Project directory not found: {project_path}")
        logger.debug("Project %s ready at %s", project.name, project_path)
        return project_path

    def clone_project(self, project_name: str, git_url: str):
        """Clone a git repo into the projects directory."""
        project_path = self._default_project_path(project_name)
        if os.path.isdir(project_path):
            logger.info("Project dir %s already exists, skipping clone", project_path)
            return
        try:
            subprocess.run(
                ["git", "clone", git_url, project_path],
                check=True, capture_output=True, text=True, timeout=120,
            )
            logger.info("Cloned project %s from %s", project_name, git_url)
        except subprocess.CalledProcessError as e:
            logger.error(
                "Git clone failed for %s: %s",
                project_name, e.stderr.strip(),
            )
            # Clean up partial/empty directory left by failed clone
            if os.path.isdir(project_path):
                shutil.rmtree(project_path, ignore_errors=True)
            raise

    def ensure_project_dir(self, project_name: str):
        """Ensure the project directory exists (for new projects only)."""
        project_path = self._default_project_path(project_name)
        os.makedirs(project_path, exist_ok=True)

    def ping(self) -> bool:
        """Check if claude CLI is reachable."""
        try:
            result = subprocess.run(
                [CLAUDE_BIN, "--version"],
                capture_output=True, text=True, timeout=10,
                env=self._clean_env(),
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            logger.debug("Claude CLI ping failed: %s", e)
            return False
