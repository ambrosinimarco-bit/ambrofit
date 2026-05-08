from fastapi import APIRouter, HTTPException
from datetime import date
from backend.database.client import get_supabase
from backend.database.models import DailyHealthCreate, DailyHealthOut

router = APIRouter(prefix="/api/health", tags=["health"])


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
