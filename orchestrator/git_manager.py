"""Git Manager — read-only git operations via temporary Docker containers."""

import logging
import os

import docker
from docker.errors import ContainerError, NotFound

from config import HOST_USER_UID

logger = logging.getLogger("orchestrator.git")

# Use a lightweight image for git operations
GIT_IMAGE = "alpine/git"

# Host path for bind-mounting into git containers
_HOST_PROJECTS = os.environ.get("HOST_PROJECTS_DIR", "/projects")


class GitManager:
    """Read-only git operations executed inside temporary containers."""

    def __init__(self):
        self.docker_client = docker.from_env()

    def _run_git(self, project_name: str, git_args: str, timeout: int = 30) -> str:
        """Run a git command in a temporary container against a project volume."""
        try:
            output = self.docker_client.containers.run(
                image=GIT_IMAGE,
                command=git_args,
                volumes={_HOST_PROJECTS: {"bind": "/projects", "mode": "ro"}},
                working_dir=f"/projects/{project_name}",
                user=f"{HOST_USER_UID}:{HOST_USER_UID}",
                environment={
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "safe.directory",
                    "GIT_CONFIG_VALUE_0": f"/projects/{project_name}",
                },
                auto_remove=True,
                stdout=True,
                stderr=True,
            )
            return output.decode("utf-8", errors="replace").strip()
        except ContainerError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            logger.warning("Git command failed for %s: %s", project_name, stderr)
            return f"ERROR: {stderr}"
        except Exception as e:
            logger.exception("Git operation failed for %s", project_name)
            return f"ERROR: {str(e)}"

    def _run_git_rw(self, project_name: str, command: str) -> str:
        """Run a git command with read-write access (for merges)."""
        try:
            output = self.docker_client.containers.run(
                image=GIT_IMAGE,
                entrypoint=["sh", "-c"],
                command=[command],
                volumes={_HOST_PROJECTS: {"bind": "/projects", "mode": "rw"}},
                working_dir=f"/projects/{project_name}",
                user=f"{HOST_USER_UID}:{HOST_USER_UID}",
                environment={
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "safe.directory",
                    "GIT_CONFIG_VALUE_0": f"/projects/{project_name}",
                },
                auto_remove=True,
                stdout=True,
                stderr=True,
            )
            return output.decode("utf-8", errors="replace").strip()
        except ContainerError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            logger.warning("Git RW command failed for %s: %s", project_name, stderr)
            return f"ERROR: {stderr}"
        except Exception as e:
            logger.exception("Git RW operation failed for %s", project_name)
            return f"ERROR: {str(e)}"

    def get_log(self, project_name: str, limit: int = 30) -> list[dict]:
        """Get recent commits for a project."""
        # Use a delimiter that won't appear in commit messages
        sep = "|||"
        fmt = f"%H{sep}%an{sep}%ae{sep}%ai{sep}%s"
        raw = self._run_git(project_name, f"log --format={fmt} -n {limit}")
        if raw.startswith("ERROR:"):
            return []

        commits = []
        for line in raw.splitlines():
            parts = line.split(sep)
            if len(parts) >= 5:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "email": parts[2],
                    "date": parts[3],
                    "message": parts[4],
                })
        return commits

    def get_branches(self, project_name: str) -> list[dict]:
        """Get branches for a project."""
        raw = self._run_git(project_name, "branch -a --format=%(refname:short)|||%(objectname:short)|||%(HEAD)")
        if raw.startswith("ERROR:"):
            return []

        branches = []
        for line in raw.splitlines():
            parts = line.split("|||")
            if len(parts) >= 3:
                branches.append({
                    "name": parts[0].strip(),
                    "commit": parts[1].strip(),
                    "current": parts[2].strip() == "*",
                })
            elif len(parts) >= 1:
                branches.append({"name": parts[0].strip(), "commit": "", "current": False})
        return branches

    def get_status(self, project_name: str) -> dict:
        """Get git status for a project: branch, staged, unstaged, untracked."""
        # Current branch
        branch = self._run_git(project_name, "branch --show-current")
        if branch.startswith("ERROR:"):
            branch = "unknown"

        # Porcelain status for reliable parsing
        raw = self._run_git(project_name, "status --porcelain")
        if raw.startswith("ERROR:"):
            return {"branch": branch, "clean": True, "staged": [], "unstaged": [], "untracked": []}

        staged = []
        unstaged = []
        untracked = []
        for line in raw.splitlines():
            if len(line) < 3:
                continue
            x, y = line[0], line[1]
            path = line[3:]
            if x == "?":
                untracked.append(path)
            else:
                if x not in (" ", "?"):
                    staged.append({"status": x, "path": path})
                if y not in (" ", "?"):
                    unstaged.append({"status": y, "path": path})

        clean = len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0
        return {
            "branch": branch,
            "clean": clean,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
        }

    def get_diff(self, project_name: str, ref: str = "HEAD") -> str:
        """Get diff for a ref."""
        return self._run_git(project_name, f"diff {ref}")

    def merge_branch(self, project_name: str, branch: str) -> dict:
        """Merge a branch into the current branch. Returns result dict."""
        # First check current branch
        current = self._run_git(project_name, "branch --show-current")
        if current.startswith("ERROR:"):
            return {"success": False, "error": current, "current_branch": "unknown"}

        # Attempt merge with read-write access
        cmd = (
            f"git config user.name 'CC Orchestrator' && "
            f"git config user.email 'cc-orchestrator@localhost' && "
            f"git merge {branch} --no-edit"
        )
        result = self._run_git_rw(project_name, cmd)

        if result.startswith("ERROR:"):
            # Check if it's a merge conflict
            if "CONFLICT" in result or "conflict" in result:
                # Abort the failed merge
                self._run_git_rw(project_name, "git merge --abort")
                return {
                    "success": False,
                    "error": "Merge conflict — manual resolution required",
                    "detail": result,
                    "current_branch": current,
                    "merged_branch": branch,
                }
            return {"success": False, "error": result, "current_branch": current}

        return {
            "success": True,
            "message": result,
            "current_branch": current,
            "merged_branch": branch,
        }
