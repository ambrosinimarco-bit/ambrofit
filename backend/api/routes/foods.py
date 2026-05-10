import base64 as _b64
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.database.client import get_supabase

router = APIRouter(prefix="/api/foods", tags=["foods"])


class FoodItemCreate(BaseModel):
    user_id: str
    name: str
    brand: str | None = None
    calories_per_100g: float | None = None
    protein_per_100g: float | None = None
    carbs_per_100g: float | None = None
    fat_per_100g: float | None = None
    fiber_per_100g: float | None = None
    source: str = "manual"


@router.get("/")
def list_foods(user_id: str, search: str = ""):
    db = get_supabase()
    q = db.table("food_items").select("*").eq("user_id", user_id)
    if search:
        q = q.ilike("name", f"%{search}%")
    return q.order("name").execute().data or []


@router.post("/")
def create_food(item: FoodItemCreate):
    from backend.services.food_service import upsert_food_item
    db = get_supabase()
    upsert_food_item(
        db, item.user_id, item.name, item.source,
        calories_per_100g=item.calories_per_100g,
        protein_per_100g=item.protein_per_100g,
        carbs_per_100g=item.carbs_per_100g,
        fat_per_100g=item.fat_per_100g,
        fiber_per_100g=item.fiber_per_100g,
        brand=item.brand,
    )
    res = db.table("food_items").select("*") \
        .eq("user_id", item.user_id).ilike("name", item.name).limit(1).execute()
    return res.data[0] if res.data else {}


@router.put("/{food_id}")
def update_food(food_id: str, item: FoodItemCreate):
    db = get_supabase()
    fields = {k: v for k, v in {
        "name":              item.name.strip(),
        "brand":             item.brand,
        "calories_per_100g": item.calories_per_100g,
        "protein_per_100g":  item.protein_per_100g,
        "carbs_per_100g":    item.carbs_per_100g,
        "fat_per_100g":      item.fat_per_100g,
        "fiber_per_100g":    item.fiber_per_100g,
        "source":            item.source,
    }.items() if v is not None}
    res = db.table("food_items").update(fields).eq("id", food_id).execute()
    return res.data[0] if res.data else {}


@router.delete("/{food_id}")
def delete_food(food_id: str):
    db = get_supabase()
    db.table("food_items").delete().eq("id", food_id).execute()
    return {"ok": True}


class PhotoAnalyzeRequest(BaseModel):
    image_b64: str


@router.post("/analyze-photo")
def analyze_food_photo_route(req: PhotoAnalyzeRequest):
    from backend.services.claude_service import analyze_nutrition_label
    try:
        image_bytes = _b64.b64decode(req.image_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Immagine non valida")
    return analyze_nutrition_label(image_bytes)
