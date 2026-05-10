from __future__ import annotations


def upsert_food_item(
    db,
    user_id: str,
    name: str,
    source: str,
    *,
    calories_per_100g: float | None = None,
    protein_per_100g: float | None = None,
    carbs_per_100g: float | None = None,
    fat_per_100g: float | None = None,
    fiber_per_100g: float | None = None,
    brand: str | None = None,
) -> None:
    """Insert a food item into the personal database if not already present.

    Uses case-insensitive name match per user to avoid duplicates.
    Silently skips if there is no meaningful nutritional data.
    """
    if not (calories_per_100g or protein_per_100g or carbs_per_100g):
        return
    try:
        existing = db.table("food_items").select("id") \
            .eq("user_id", user_id).ilike("name", name.strip()).limit(1).execute()
        if existing.data:
            return
        row = {k: v for k, v in {
            "user_id":           user_id,
            "name":              name.strip(),
            "brand":             brand,
            "calories_per_100g": round(calories_per_100g, 1) if calories_per_100g else None,
            "protein_per_100g":  round(protein_per_100g, 1) if protein_per_100g else None,
            "carbs_per_100g":    round(carbs_per_100g, 1) if carbs_per_100g else None,
            "fat_per_100g":      round(fat_per_100g, 1) if fat_per_100g else None,
            "fiber_per_100g":    round(fiber_per_100g, 1) if fiber_per_100g else None,
            "source":            source,
        }.items() if v is not None}
        db.table("food_items").insert(row).execute()
    except Exception:
        pass  # never block the main flow


def lookup_food_item(db, user_id: str, query: str) -> dict | None:
    """Return the best-matching food_item for the query string, or None."""
    try:
        res = db.table("food_items").select("*") \
            .eq("user_id", user_id).ilike("name", f"%{query.strip()}%") \
            .order("name").limit(1).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def calculate_for_quantity(item: dict, quantity_g: float) -> dict:
    """Scale per-100g nutritional values to the given quantity."""
    f = quantity_g / 100
    return {
        "calories":  round((item.get("calories_per_100g") or 0) * f, 1),
        "protein_g": round((item.get("protein_per_100g") or 0) * f, 1),
        "carbs_g":   round((item.get("carbs_per_100g") or 0) * f, 1),
        "fat_g":     round((item.get("fat_per_100g") or 0) * f, 1),
        "fiber_g":   round((item.get("fiber_per_100g") or 0) * f, 1),
    }
