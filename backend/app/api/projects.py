import uuid

from fastapi import APIRouter, status

from app.api.deps import DB
from app.models.enums import ProjectStatus
from app.schemas.project import ProjectCreate, ProjectOut, ProjectStats, ProjectUpdate
from app.services import projects

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(db: DB, status: ProjectStatus | None = None):
    return projects.list_projects(db, status)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(db: DB, body: ProjectCreate):
    return projects.create_project(db, body)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(db: DB, project_id: uuid.UUID):
    return projects.get_project(db, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(db: DB, project_id: uuid.UUID, body: ProjectUpdate):
    return projects.update_project(db, project_id, body)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(db: DB, project_id: uuid.UUID):
    projects.delete_project(db, project_id)


@router.get("/{project_id}/stats", response_model=ProjectStats)
def project_stats(db: DB, project_id: uuid.UUID):
    return projects.project_stats(db, project_id)
