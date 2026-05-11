import logging
from fastapi import APIRouter, HTTPException, Request
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from backend.database.client import get_supabase
from backend.database.models import DailyHealthCreate, DailyHealthOut

router = APIRouter(prefix="/api/health", tags=["health"])
logger = logging.getLogger(__name__)


class IOSHealthSync(BaseModel):
    user_id: str
    calories: Optional[int] = None           # calorie attive (movimento + sport)
    resting_calories: Optional[int] = None   # calorie a riposo (BMR)
    steps: Optional[int] = None
    timestamp: Optional[str] = None          # ISO 8601, e.g. "2026-05-10T16:00:00"


@router.post("/sync-calories")
async def sync_ios_calories(payload: IOSHealthSync, request: Request):
    """Receive health data from iOS Shortcuts and update daily_health."""
    raw_body = await request.body()
    logger.info("[sync-calories] raw body: %s", raw_body.decode())
    logger.info("[sync-calories] parsed: user_id=%s calories=%s resting_calories=%s steps=%s timestamp=%s",
                payload.user_id, payload.calories, payload.resting_calories, payload.steps, payload.timestamp)

    db = get_supabase()

    health_date = date.today().isoformat()
    if payload.timestamp:
        try:
            health_date = datetime.fromisoformat(payload.timestamp).date().isoformat()
        except ValueError:
            logger.warning("[sync-calories] invalid timestamp %r, using today", payload.timestamp)

    update_fields: dict = {}
    if payload.calories is not None and payload.resting_calories is not None:
        update_fields["total_calories_iphone"] = payload.calories + payload.resting_calories
    elif payload.calories is not None:
        update_fields["total_calories_iphone"] = payload.calories
    if payload.steps is not None:
        update_fields["steps"] = payload.steps

    logger.info("[sync-calories] update_fields=%s date=%s", update_fields, health_date)

    if not update_fields:
        return {"status": "ok", "message": "nessun dato da aggiornare"}

    existing = (
        db.table("daily_health")
        .select("id")
        .eq("user_id", payload.user_id)
        .eq("health_date", health_date)
        .limit(1)
        .execute()
    )

    row = {"user_id": payload.user_id, "health_date": health_date, **update_fields}
    if existing.data:
        db.table("daily_health").update(update_fields).eq("id", existing.data[0]["id"]).execute()
    else:
        db.table("daily_health").insert(row).execute()

    return {
        "status": "ok",
        "message": "dati aggiornati",
        "date": health_date,
        "total_calories_iphone": update_fields.get("total_calories_iphone"),
        "steps": update_fields.get("steps"),
    }


@router.get("/")
def list_health(user_id: str, days: int = 30):
    db = get_supabase()
    from datetime import timedelta
    since = (date.today() - timedelta(days=days)).isoformat()
    result = db.table("daily_health").select("*").eq("user_id", user_id).gte("health_date", since).order("health_date", desc=True).execute()
    return result.data or []


@router.get("/today")
def get_today(user_id: str):
    db = get_supabase()
    result = db.table("daily_health").select("*").eq("user_id", user_id).eq("health_date", date.today().isoformat()).limit(1).execute()
    return (result.data or [{}])[0]


@router.post("/", response_model=DailyHealthOut)
def upsert_health(health: DailyHealthCreate):
    db = get_supabase()
    existing = db.table("daily_health").select("id").eq("user_id", health.user_id).eq("health_date", health.health_date.isoformat()).execute()

    data = {k: v for k, v in health.model_dump(mode="json").items() if v is not None}

    if existing.data:
        result = db.table("daily_health").update(data).eq("id", existing.data[0]["id"]).execute()
    else:
        result = db.table("daily_health").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio")
    return result.data[0]


@router.put("/{health_id}")
def update_health(health_id: str, data: dict):
    db = get_supabase()
    safe_fields = {"weight_kg", "sleep_hours", "steps", "body_battery", "hrv_ms",
                   "stress_score", "resting_hr", "total_calories_iphone", "notes"}
    safe_data = {k: v for k, v in data.items() if k in safe_fields and v is not None}
    result = db.table("daily_health").update(safe_data).eq("id", health_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Record non trovato")
    return result.data[0]


@router.get("/weight-trend")
def weight_trend(user_id: str, days: int = 60):
    from backend.services.nutrition_service import get_weight_trend
    return get_weight_trend(user_id, days)
