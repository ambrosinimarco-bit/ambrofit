import logging
from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.database.client import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/objectives", tags=["objectives"])


class ObjectiveCreate(BaseModel):
    title: str
    description: Optional[str] = None
    type: str = "open"
    target_date: Optional[date] = None
    target_value: Optional[float] = None
    target_unit: Optional[str] = None

class ObjectiveUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    target_date: Optional[date] = None
    target_value: Optional[float] = None
    target_unit: Optional[str] = None

class ActivityLogCreate(BaseModel):
    log_date: Optional[date] = None
    session_id: Optional[str] = None
    activity_id: Optional[str] = None
    rpe_actual: Optional[int] = None
    feeling: Optional[int] = None
    completed: bool = True
    notes: Optional[str] = None

class CheckinCreate(BaseModel):
    checkin_date: Optional[date] = None
    sleep_quality: Optional[int] = None
    energy_level: Optional[int] = None
    muscle_soreness: Optional[int] = None
    motivation: Optional[int] = None
    note: Optional[str] = None


@router.get("/{user_id}")
def get_objectives(user_id: str, status: Optional[str] = None):
    db = get_supabase()
    query = db.table("v_objective_progress").select("*").eq("user_id", user_id)
    if status:
        query = query.eq("status", status)
    result = query.order("target_date", desc=False, nullsfirst=False).execute()
    return result.data or []

@router.post("/{user_id}")
def create_objective(user_id: str, body: ObjectiveCreate):
    db = get_supabase()
    data = body.model_dump(exclude_none=True)
    data["user_id"] = user_id
    if data.get("target_date"):
        data["target_date"] = str(data["target_date"])
    result = db.table("objectives").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nella creazione dell'obiettivo")
    return result.data[0]

@router.patch("/{objective_id}")
def update_objective(objective_id: str, body: ObjectiveUpdate):
    db = get_supabase()
    data = body.model_dump(exclude_none=True)
    if data.get("target_date"):
        data["target_date"] = str(data["target_date"])
    result = db.table("objectives").update(data).eq("id", objective_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Obiettivo non trovato")
    return result.data[0]

@router.delete("/{objective_id}")
def delete_objective(objective_id: str):
    db = get_supabase()
    db.table("objectives").delete().eq("id", objective_id).execute()
    return {"ok": True}

@router.post("/{user_id}/log")
def create_activity_log(user_id: str, body: ActivityLogCreate):
    db = get_supabase()
    data = body.model_dump(exclude_none=True)
    data["user_id"] = user_id
    if data.get("log_date"):
        data["log_date"] = str(data["log_date"])
    result = db.table("activity_logs").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio del log")
    return result.data[0]

@router.get("/{user_id}/logs")
def get_activity_logs(user_id: str, days: int = 30):
    db = get_supabase()
    since = (date.today() - timedelta(days=days)).isoformat()
    result = db.table("activity_logs").select("*")\
        .eq("user_id", user_id)\
        .gte("log_date", since)\
        .order("log_date", desc=True)\
        .execute()
    return result.data or []

@router.post("/{user_id}/checkin")
def save_checkin(user_id: str, body: CheckinCreate):
    db = get_supabase()
    data = body.model_dump(exclude_none=True)
    data["user_id"] = user_id
    data["checkin_date"] = str(data.get("checkin_date", date.today()))
    result = db.table("daily_checkin").upsert(
        data, on_conflict="user_id,checkin_date"
    ).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio del check-in")
    return result.data[0]

@router.get("/{user_id}/checkin")
def get_checkins(user_id: str, days: int = 30):
    db = get_supabase()
    since = (date.today() - timedelta(days=days)).isoformat()
    result = db.table("daily_checkin").select("*")\
        .eq("user_id", user_id)\
        .gte("checkin_date", since)\
        .order("checkin_date", desc=True)\
        .execute()
    return result.data or []

@router.get("/{user_id}/checkin/today")
def get_today_checkin(user_id: str):
    db = get_supabase()
    result = db.table("v_daily_readiness").select("*")\
        .eq("user_id", user_id)\
        .eq("checkin_date", date.today().isoformat())\
        .limit(1)\
        .execute()
    return result.data[0] if result.data else None
