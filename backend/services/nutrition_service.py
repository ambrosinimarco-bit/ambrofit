import logging
from datetime import date
from backend.database.client import get_supabase

logger = logging.getLogger(__name__)


def calculate_bmr(weight_kg: float, height_cm: float, age: int, sex: str = "male") -> int:
    """Mifflin-St Jeor BMR formula."""
    bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return round(bmr + 5 if sex == "male" else bmr - 161)


def calc_dynamic_macros(calories_out: float, weight_kg: float) -> tuple[int, int, int]:
    """Calcola target macronutrienti dinamici per ciclista in allenamento.
    Returns (protein_g, carbs_g, fat_g).
    """
    protein_g = round(weight_kg * 2)           # 2 g/kg fisso
    fat_g = round(calories_out * 0.25 / 9)     # 25% delle kcal totali
    carbs_g = max(50, round((calories_out - protein_g * 4 - fat_g * 9) / 4))
    return protein_g, carbs_g, fat_g


def get_daily_summary(user_id: str, target_date: date) -> dict:
    db = get_supabase()
    date_str = target_date.isoformat()

    meals = db.table("meals").select("*").eq("user_id", user_id).eq("meal_date", date_str).execute()
    activities = db.table("activities").select("*").eq("user_id", user_id).eq("activity_date", date_str).execute()
    try:
        health_result = db.table("daily_health").select("*").eq("user_id", user_id).eq("health_date", date_str).limit(1).execute()
    except Exception:
        # Fallback for older DB schemas — keep total_calories_iphone in the list
        health_cols = (
            "id,user_id,health_date,weight_kg,sleep_hours,steps,"
            "body_battery,hrv_ms,stress_score,resting_hr,notes,"
            "total_calories_iphone,created_at"
        )
        health_result = db.table("daily_health").select(health_cols).eq("user_id", user_id).eq("health_date", date_str).limit(1).execute()
    user_result = db.table("user_profiles").select("*").eq("id", user_id).limit(1).execute()

    meal_list = meals.data or []
    activity_list = activities.data or []
    health_data = (health_result.data or [{}])[0]
    user_data = (user_result.data or [{}])[0]

    calories_in = sum(m.get("calories", 0) for m in meal_list)
    protein = sum(m.get("protein_g", 0) for m in meal_list)
    carbs = sum(m.get("carbs_g", 0) for m in meal_list)
    fat = sum(m.get("fat_g", 0) for m in meal_list)
    fiber = sum(m.get("fiber_g", 0) for m in meal_list)
    activities_calories = sum(a.get("calories", 0) or 0 for a in activity_list)

    # ── Weight resolution (used by both BMR and macro targets) ──────────────
    # 1. today's daily_health  2. latest daily_health with a value  3. user_profiles
    weight_kg = health_data.get("weight_kg")
    if weight_kg is None:
        latest = db.table("daily_health")\
            .select("weight_kg")\
            .eq("user_id", user_id)\
            .not_.is_("weight_kg", "null")\
            .order("health_date", desc=True)\
            .limit(1)\
            .execute()
        weight_kg = (latest.data or [{}])[0].get("weight_kg")
    if weight_kg is None:
        weight_kg = user_data.get("weight_kg")

    # ── BMR ─────────────────────────────────────────────────────────────────
    height = user_data.get("height_cm")
    age = user_data.get("age")
    bmr = calculate_bmr(float(weight_kg), height, age) if (weight_kg and height and age) else None
    logger.debug("BMR inputs: weight_kg=%s height_cm=%s age=%s → bmr=%s", weight_kg, height, age, bmr)

    # ── Calorie bruciate ─────────────────────────────────────────────────────
    # Priority: 1) total_calories_iphone  2) active_calories_manual  3) bmr+activities
    # active_calories_manual already includes basal burn — do NOT add bmr on top.
    total_calories_iphone = health_data.get("total_calories_iphone")
    active_calories_manual = health_data.get("active_calories_manual")
    if total_calories_iphone:
        calories_out = total_calories_iphone
    elif active_calories_manual:
        calories_out = active_calories_manual
    elif bmr:
        calories_out = bmr + activities_calories
    else:
        calories_out = activities_calories

    # ── Stima calorie a fine giornata ────────────────────────────────────────
    # Proietta le calorie attuali al ritmo corrente fino alle ore 22:00.
    # Usata solo se active_calories_manual è presente e la data è oggi.
    estimated_eod_calories: int | None = None
    if active_calories_manual and target_date == date.today():
        from datetime import datetime as _dt
        now = _dt.now()
        elapsed_hours = now.hour + now.minute / 60
        if elapsed_hours >= 1:
            estimated_eod_calories = max(1900, round(active_calories_manual / elapsed_hours * 22))

    calorie_goal = user_data.get("daily_calorie_goal", 2400)

    # ── Macro targets ────────────────────────────────────────────────────────
    _has_reliable_cal = bool(total_calories_iphone or bmr or active_calories_manual)
    if _has_reliable_cal and weight_kg:
        protein_goal, carbs_goal, fat_goal = calc_dynamic_macros(calories_out, float(weight_kg))
        macro_targets_dynamic = True
        logger.info(
            "macro targets DYNAMIC | cal_iphone=%s bmr=%s acm=%s cal_out=%.0f weight=%.1f "
            "→ P=%dg C=%dg F=%dg",
            total_calories_iphone, bmr, active_calories_manual, calories_out, weight_kg,
            protein_goal, carbs_goal, fat_goal,
        )
    else:
        protein_goal = user_data.get("protein_goal_g", 150)
        carbs_goal = user_data.get("carbs_goal_g", 280)
        fat_goal = user_data.get("fat_goal_g", 75)
        macro_targets_dynamic = False
        logger.warning(
            "macro targets STATIC (fallback) | cal_iphone=%s bmr=%s acm=%s weight_kg=%s "
            "→ has_reliable_cal=%s weight_ok=%s",
            total_calories_iphone, bmr, active_calories_manual, weight_kg,
            _has_reliable_cal, bool(weight_kg),
        )

    return {
        "date": date_str,
        "calories_in": round(calories_in, 1),
        "calories_out": round(calories_out, 1),
        "activities_calories": round(activities_calories, 1),
        "bmr": bmr,
        "total_calories_iphone": total_calories_iphone,
        "active_calories_manual": active_calories_manual,
        "estimated_eod_calories": estimated_eod_calories,
        "net_calories": round(calories_in - calories_out, 1),
        "calorie_goal": calorie_goal,
        "calorie_balance": round(calories_in - calorie_goal, 1),
        "protein_g": round(protein, 1),
        "carbs_g": round(carbs, 1),
        "fat_g": round(fat, 1),
        "fiber_g": round(fiber, 1),
        "protein_goal_g": protein_goal,
        "carbs_goal_g": carbs_goal,
        "fat_goal_g": fat_goal,
        "macro_targets_dynamic": macro_targets_dynamic,
        "weight_kg": weight_kg,
        "steps": health_data.get("steps"),
        "sleep_hours": health_data.get("sleep_hours"),
        "body_battery": health_data.get("body_battery"),
        "hrv_ms": health_data.get("hrv_ms"),
        "stress_score": health_data.get("stress_score"),
        "meals": meal_list,
        "activities": activity_list,
    }


def get_weekly_summary(user_id: str, week_start: date) -> list[dict]:
    from datetime import timedelta
    return [get_daily_summary(user_id, week_start + timedelta(days=i)) for i in range(7)]


def get_weight_trend(user_id: str, days: int = 30) -> list[dict]:
    from datetime import timedelta
    db = get_supabase()
    since = (date.today() - timedelta(days=days)).isoformat()

    result = db.table("daily_health")\
        .select("health_date,weight_kg")\
        .eq("user_id", user_id)\
        .gte("health_date", since)\
        .not_.is_("weight_kg", "null")\
        .order("health_date")\
        .execute()

    return result.data or []
