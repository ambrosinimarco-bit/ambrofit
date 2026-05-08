from fastapi import APIRouter, HTTPException
from datetime import date
from backend.database.client import get_supabase
from backend.database.models import ActivityCreate, ActivityOut

router = APIRouter(prefix="/api/activities", tags=["activities"])


@router.get("/")
def list_activities(user_id: str, activity_date: date | None = None, days: int = 7):
    db = get_supabase()
    query = db.table("activities").select("*").eq("user_id", user_id)
    if activity_date:
        query = query.eq("activity_date", activity_date.isoformat())
    else:
        from datetime import timedelta
        since = (date.today() - timedelta(days=days)).isoformat()
        query = query.gte("activity_date", since)
    result = query.order("activity_date", desc=True).execute()
    return result.data or []


@router.post("/", response_model=ActivityOut)
def create_activity(activity: ActivityCreate):
    db = get_supabase()
    result = db.table("activities").insert(activity.model_dump()).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio")
    return result.data[0]


@router.put("/{activity_id}")
def update_activity(activity_id: str, activity: ActivityCreate):
    db = get_supabase()
    result = db.table("activities").update(activity.model_dump()).eq("id", activity_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Attività non trovata")
    return result.data[0]


@router.delete("/{activity_id}")
def delete_activity(activity_id: str):
    db = get_supabase()
    db.table("activities").delete().eq("id", activity_id).execute()
    return {"ok": True}


@router.patch("/{activity_id}/checkin")
def checkin_activity(activity_id: str, data: dict):
    db = get_supabase()
    update_data = {}
    if "rpe" in data:
        update_data["rpe"] = int(data["rpe"])
    if "physical_notes" in data:
        update_data["physical_notes"] = data["physical_notes"]
    update_data["check_in_done"] = True
    result = db.table("activities").update(update_data).eq("id", activity_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Attività non trovata")
    return result.data[0]
