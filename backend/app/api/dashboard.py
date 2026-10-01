from fastapi import APIRouter

from app.api.deps import DB, Now, Settings
from app.schemas.dashboard import TodayDashboard
from app.services import dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/today", response_model=TodayDashboard)
def today(db: DB, now: Now, settings: Settings):
    return dashboard.today(db, now, settings)
