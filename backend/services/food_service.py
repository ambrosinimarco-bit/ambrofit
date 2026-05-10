from __future__ import annotations
import re

# ── Name cleaning ─────────────────────────────────────────────────────────────

_MEAL_CONTEXT_RE = re.compile(
    r'\b(?:colazione|pranzo|cena|spuntino|merenda|dessert|breakfast|lunch|dinner|snack)\b',
    re.IGNORECASE,
)
_QUANTITY_RE = re.compile(
    r'\b\d+(?:[.,]\d+)?\s*(?:g|gr|grammi?|kg|ml|cl|dl|l|litri?|porzioni?|fett[ae]|cucchiai[no]?|cucchiaini?|tazz[ae])\b',
    re.IGNORECASE,
)
# Filler words that are never part of a food name.
# Prepositions like "di" are intentionally excluded: they ARE part of names
# ("petto di pollo", "olio di oliva") and are only noise at the string edges.
_FILLER_RE = re.compile(
    r'\b(?:'
    r'ho\s+mangiato|ho\s+bevuto|ho\s+preso|sto\s+mangiando'
    r'|mangiato|bevuto|mangio|bevo'
    r'|un\s+po\b|un\s+pochino'             # "un po'" residue
    r'|come|oggi|stamattina|stamani|ieri|stasera|adesso|ora'
    r'|circa|quasi|solo|solamente|appena|già'
    r'|questo|questa|questi|queste|quello|quella'
    r')\b',
    re.IGNORECASE,
)
# Prepositions/articles that are noise only at the START of the cleaned string
_LEADING_PREP_RE = re.compile(
    r'^(?:di|da|per|con|a|e|ed|un[ao]?|del|della|dello|degli?|delle?|dei?|il|la|lo|le|gli|i|al|alla|allo)\s+',
    re.IGNORECASE,
)
# Prepositions/articles that are noise only at the END of the cleaned string
_TRAILING_PREP_RE = re.compile(
    r'\s+(?:di|da|per|con|a|e|ed|al|alla|allo|del|della|dello|degli?|delle?|il|la|lo|le|gli|i)$',
    re.IGNORECASE,
)


def clean_food_name(name: str) -> str:
    """Strip meal-time context, quantities and filler words; title-case the result."""
    s = _MEAL_CONTEXT_RE.sub(' ', name)
    s = _QUANTITY_RE.sub(' ', s)
    s = _FILLER_RE.sub(' ', s)
    s = re.sub(r'\s{2,}', ' ', s).strip(" ,'\"")
    # Strip leading/trailing prepositions left behind after previous substitutions
    s = _LEADING_PREP_RE.sub('', s).strip()
    s = _TRAILING_PREP_RE.sub('', s).strip()
    return ' '.join(w.capitalize() for w in s.split()) if s else ''


# ── Public API ────────────────────────────────────────────────────────────────

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
    """Upsert a food item into the personal database.

    The name is cleaned (meal-time context, quantities, filler words removed)
    before the case-insensitive duplicate check and before saving.
    Silently skips if there is no meaningful nutritional data or if the
    cleaned name is empty.
    """
    if not (calories_per_100g or protein_per_100g or carbs_per_100g):
        return
    clean_name = clean_food_name(name)
    if not clean_name:
        return
    try:
        existing = db.table("food_items").select("id") \
            .eq("user_id", user_id).ilike("name", clean_name).limit(1).execute()
        nutrient_fields = {k: v for k, v in {
            "calories_per_100g": round(calories_per_100g, 1) if calories_per_100g else None,
            "protein_per_100g":  round(protein_per_100g, 1) if protein_per_100g else None,
            "carbs_per_100g":    round(carbs_per_100g, 1) if carbs_per_100g else None,
            "fat_per_100g":      round(fat_per_100g, 1) if fat_per_100g else None,
            "fiber_per_100g":    round(fiber_per_100g, 1) if fiber_per_100g else None,
            "source":            source,
        }.items() if v is not None}
        if existing.data:
            db.table("food_items").update(nutrient_fields) \
                .eq("id", existing.data[0]["id"]).execute()
        else:
            insert_row = {"user_id": user_id, "name": clean_name, **nutrient_fields}
            if brand:
                insert_row["brand"] = brand
            db.table("food_items").insert(insert_row).execute()
    except Exception:
        pass  # never block the main flow


def extract_quantity_g(text: str) -> float | None:
    """Extract the first gram quantity from a free-form text string."""
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*g(?:rammi?)?\b', text, re.IGNORECASE)
    return float(m.group(1).replace(',', '.')) if m else None


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
