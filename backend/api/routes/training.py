import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
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


class ZwoGenerateRequest(BaseModel):
    user_id: str
    session_type: str   # recovery | base | sweetspot | tempo | vo2max
    duration_min: int


_SESSION_LABELS = {
    "recovery":  "recupero Z1",
    "base":      "base endurance Z2",
    "sweetspot": "sweet spot",
    "tempo":     "tempo",
    "vo2max":    "VO2max intervalli",
}


@router.post("/generate-zwo")
async def generate_zwo_endpoint(body: ZwoGenerateRequest):
    """Genera un file .zwo per MyWhoosh e lo restituisce come contenuto XML."""
    db = get_supabase()
    profile_res = db.table("user_profiles").select("ftp_watts,weight_kg")\
        .eq("id", body.user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]
    ftp = profile.get("ftp_watts") or 202
    weight_kg = float(profile.get("weight_kg") or 75.0)

    label = _SESSION_LABELS.get(body.session_type, body.session_type)
    request_text = f"sessione {label} da {body.duration_min} minuti"

    from backend.services.claude_service import plan_zwo_workout
    from backend.services.zwo_service import generate_zwo_xml, safe_filename

    try:
        workout = await asyncio.to_thread(plan_zwo_workout, request_text, ftp)
        xml_content = generate_zwo_xml(workout, ftp, weight_kg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    filename = safe_filename(workout.get("name", "Workout")) + ".zwo"
    return {"xml": xml_content, "filename": filename, "workout": workout}


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
