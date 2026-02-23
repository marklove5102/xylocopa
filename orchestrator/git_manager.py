"""Git Manager — read-only git operations via temporary Docker containers."""

import logging

import docker
from docker.errors import ContainerError, NotFound

from config import HOST_USER_UID

logger = logging.getLogger("orchestrator.git")

# Use a lightweight image for git operations
GIT_IMAGE = "alpine/git"


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
                volumes={"cc-projects": {"bind": "/projects", "mode": "ro"}},
                working_dir=f"/projects/{project_name}",
                user=f"{HOST_USER_UID}:{HOST_USER_UID}",
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
                volumes={"cc-projects": {"bind": "/projects", "mode": "rw"}},
                working_dir=f"/projects/{project_name}",
                user=f"{HOST_USER_UID}:{HOST_USER_UID}",
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
