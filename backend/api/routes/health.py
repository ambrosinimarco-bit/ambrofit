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
    active_calories: Optional[float] = None    # calorie attive aggregate per il giorno (HealthKit)
    resting_calories: Optional[float] = None   # calorie a riposo aggregate per il giorno (HealthKit)
    steps: Optional[int] = None
    timestamp: Optional[str] = None            # ISO 8601, e.g. "2026-05-10T16:00:00"


@router.post("/sync-calories")
async def sync_ios_calories(payload: IOSHealthSync, request: Request):
    """Receive aggregated daily health data from iOS Shortcuts (HealthKit) and update daily_health."""
    raw_body = await request.body()
    print(f"[sync-calories] RAW BODY: {raw_body.decode()}", flush=True)
    print(f"[sync-calories] active_calories={payload.active_calories!r}  resting_calories={payload.resting_calories!r}  steps={payload.steps!r}  timestamp={payload.timestamp!r}", flush=True)

    db = get_supabase()

    health_date = date.today().isoformat()
    if payload.timestamp:
        try:
            health_date = datetime.fromisoformat(payload.timestamp).date().isoformat()
        except ValueError:
            print(f"[sync-calories] WARNING: invalid timestamp {payload.timestamp!r}, using today", flush=True)

    update_fields: dict = {}
    if payload.active_calories is not None:
        update_fields["active_calories"] = round(payload.active_calories)
    if payload.resting_calories is not None:
        update_fields["resting_calories"] = round(payload.resting_calories)
    if payload.active_calories is not None and payload.resting_calories is not None:
        total = round(payload.active_calories + payload.resting_calories)
        print(f"[sync-calories] CALC: {payload.active_calories} + {payload.resting_calories} = {total}", flush=True)
        update_fields["total_calories_iphone"] = total
    elif payload.active_calories is not None:
        update_fields["total_calories_iphone"] = update_fields["active_calories"]
    if payload.steps is not None:
        update_fields["steps"] = payload.steps

    print(f"[sync-calories] update_fields={update_fields}  date={health_date}", flush=True)

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
        "active_calories": update_fields.get("active_calories"),
        "resting_calories": update_fields.get("resting_calories"),
        "total_calories_iphone": update_fields.get("total_calories_iphone"),
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
