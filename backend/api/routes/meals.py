from fastapi import APIRouter, HTTPException
from datetime import date
from backend.database.client import get_supabase
from backend.database.models import MealCreate, MealOut

router = APIRouter(prefix="/api/meals", tags=["meals"])


@router.get("/")
def list_meals(user_id: str, meal_date: date | None = None):
    db = get_supabase()
    query = db.table("meals").select("*").eq("user_id", user_id)
    if meal_date:
        query = query.eq("meal_date", meal_date.isoformat())
    result = query.order("created_at", desc=True).execute()
    return result.data or []


@router.post("/", response_model=MealOut)
def create_meal(meal: MealCreate):
    db = get_supabase()
    result = db.table("meals").insert(meal.model_dump()).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio")
    return result.data[0]


@router.put("/{meal_id}")
def update_meal(meal_id: str, meal: MealCreate):
    db = get_supabase()
    result = db.table("meals").update(meal.model_dump()).eq("id", meal_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Pasto non trovato")
    return result.data[0]


@router.delete("/{meal_id}")
def delete_meal(meal_id: str):
    db = get_supabase()
    db.table("meals").delete().eq("id", meal_id).execute()
    return {"ok": True}
