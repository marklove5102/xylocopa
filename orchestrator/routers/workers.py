"""Worker/process monitoring routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Project

router = APIRouter(tags=["workers"])


@router.get("/api/projects/{project_name}/worktrees")
async def list_project_worktrees(project_name: str, db: Session = Depends(get_db)):
    """List git worktrees for a specific project."""
    proj = db.get(Project, project_name)
    if not proj:
        return []
    from git_manager import GitManager
    gm = GitManager()
    return gm.get_worktrees(proj.path)
