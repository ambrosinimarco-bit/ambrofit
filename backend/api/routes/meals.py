from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import date
from backend.database.client import get_supabase
from backend.database.models import MealCreate

router = APIRouter(prefix="/api/meals", tags=["meals"])


@router.get("/")
def list_meals(user_id: str, meal_date: date | None = None):
    db = get_supabase()
    query = db.table("meals").select("*").eq("user_id", user_id)
    if meal_date:
        query = query.eq("meal_date", meal_date.isoformat())
    result = query.order("created_at", desc=True).execute()
    return result.data or []


@router.post("/")
def create_meal(meal: MealCreate):
    if not meal.calories:
        from backend.services.claude_service import analyze_food_text
        text = f"{int(meal.quantity_g)}g di {meal.name}" if meal.quantity_g else meal.name
        try:
            est = analyze_food_text(text)
            meal = meal.model_copy(update={
                "calories":  est.get("total_calories", 0),
                "protein_g": est.get("total_protein_g", 0),
                "carbs_g":   est.get("total_carbs_g", 0),
                "fat_g":     est.get("total_fat_g", 0),
                "fiber_g":   est.get("total_fiber_g", 0),
            })
        except Exception:
            pass

    db = get_supabase()
    result = db.table("meals").insert(meal.model_dump(mode="json")).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio")

    # Auto-save to personal food database when quantity is known
    if meal.quantity_g and meal.quantity_g > 0 and meal.calories:
        from backend.services.food_service import upsert_food_item
        qty = meal.quantity_g
        upsert_food_item(
            db, meal.user_id, meal.name, "manuale",
            calories_per_100g=meal.calories * 100 / qty,
            protein_per_100g=meal.protein_g * 100 / qty if meal.protein_g else None,
            carbs_per_100g=meal.carbs_g * 100 / qty if meal.carbs_g else None,
            fat_per_100g=meal.fat_g * 100 / qty if meal.fat_g else None,
            fiber_per_100g=meal.fiber_g * 100 / qty if meal.fiber_g else None,
        )

    return result.data[0]


@router.put("/{meal_id}")
def update_meal(meal_id: str, meal: MealCreate):
    db = get_supabase()
    result = db.table("meals").update(meal.model_dump(mode="json")).eq("id", meal_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Pasto non trovato")
    return result.data[0]


@router.delete("/{meal_id}")
def delete_meal(meal_id: str):
    db = get_supabase()
    db.table("meals").delete().eq("id", meal_id).execute()
    return {"ok": True}


class MealEstimateRequest(BaseModel):
    name: str
    quantity_g: float | None = None


@router.post("/estimate")
def estimate_meal(req: MealEstimateRequest):
    from backend.services.claude_service import analyze_food_text
    text = f"{int(req.quantity_g)}g di {req.name}" if req.quantity_g else req.name
    result = analyze_food_text(text)
    return {
        "calories":   result.get("total_calories", 0),
        "protein_g":  result.get("total_protein_g", 0),
        "carbs_g":    result.get("total_carbs_g", 0),
        "fat_g":      result.get("total_fat_g", 0),
        "fiber_g":    result.get("total_fiber_g", 0),
        "confidence": result.get("confidence", "low"),
    }
