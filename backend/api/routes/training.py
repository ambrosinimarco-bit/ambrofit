from fastapi import APIRouter, HTTPException
from datetime import date
from backend.database.client import get_supabase
from backend.database.models import TrainingPlanCreate, TrainingSessionCreate, PlanAdjustmentRequest
from backend.services.training_plan_service import (
    get_active_plan,
    get_plan_sessions,
    create_plan_from_claude,
    adjust_plan,
)

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/plan/{user_id}")
def get_plan(user_id: str):
    plan = get_active_plan(user_id)
    if not plan:
        return {"plan": None, "sessions": []}
    sessions = get_plan_sessions(plan["id"])
    return {"plan": plan, "sessions": sessions}


@router.post("/plan/{user_id}/generate")
def generate_plan(user_id: str, request: str):
    return create_plan_from_claude(user_id, request)


@router.post("/plan/{user_id}/adjust")
def adjust_plan_endpoint(user_id: str, adjustment: PlanAdjustmentRequest):
    return adjust_plan(
        user_id,
        adjustment.reason,
        adjustment.detail or "",
        adjustment.skip_days or 0,
        adjustment.reduce_intensity or False,
    )


@router.patch("/session/{session_id}")
def update_session(session_id: str, data: dict):
    db = get_supabase()
    allowed = {"status", "notes", "description", "intensity", "duration_target_min"}
    safe_data = {k: v for k, v in data.items() if k in allowed}
    result = db.table("training_sessions").update(safe_data).eq("id", session_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    return result.data[0]


@router.get("/sessions/{user_id}")
def get_sessions(user_id: str, from_date: date | None = None, days: int = 14):
    db = get_supabase()
    from datetime import timedelta
    start = (from_date or date.today()).isoformat()
    end = ((from_date or date.today()) + timedelta(days=days)).isoformat()

    result = db.table("training_sessions")\
        .select("*")\
        .eq("user_id", user_id)\
        .gte("scheduled_date", start)\
        .lte("scheduled_date", end)\
        .order("scheduled_date")\
        .execute()
    return result.data or []
