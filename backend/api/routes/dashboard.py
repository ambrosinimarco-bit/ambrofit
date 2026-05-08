from fastapi import APIRouter
from datetime import date, timedelta
from backend.services.nutrition_service import get_daily_summary, get_weekly_summary, get_weight_trend
from backend.services.claude_service import suggest_exercises
from backend.database.client import get_supabase

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/today/{user_id}")
def dashboard_today(user_id: str, target_date: date | None = None):
    return get_daily_summary(user_id, target_date or date.today())


@router.get("/week/{user_id}")
def dashboard_week(user_id: str, week_offset: int = 0):
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) - timedelta(weeks=week_offset)
    return {
        "week_start": week_start.isoformat(),
        "days": get_weekly_summary(user_id, week_start),
    }


@router.get("/weight-trend/{user_id}")
def weight_trend(user_id: str, days: int = 60):
    return get_weight_trend(user_id, days)


@router.get("/calorie-trend/{user_id}")
def calorie_trend(user_id: str, days: int = 30):
    from backend.services.nutrition_service import calculate_bmr
    db = get_supabase()
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    today_str = date.today().isoformat()

    meals_raw = db.table("meals").select("meal_date,calories")\
        .eq("user_id", user_id).gte("meal_date", since).lte("meal_date", today_str).execute()
    acts_raw = db.table("activities").select("activity_date,calories")\
        .eq("user_id", user_id).gte("activity_date", since).lte("activity_date", today_str).execute()
    try:
        health_raw = db.table("daily_health").select("health_date,total_calories_iphone")\
            .eq("user_id", user_id).gte("health_date", since).lte("health_date", today_str).execute()
    except Exception:
        health_raw = type("R", (), {"data": []})()  # colonna non ancora migrata
    user = db.table("user_profiles")\
        .select("daily_calorie_goal,weight_kg,height_cm,age")\
        .eq("id", user_id).single().execute()

    profile = user.data or {}
    calorie_goal = profile.get("daily_calorie_goal", 2400)
    bmr = calculate_bmr(profile["weight_kg"], profile["height_cm"], profile["age"]) \
        if (profile.get("weight_kg") and profile.get("height_cm") and profile.get("age")) else None

    cal_in: dict[str, float] = {}
    for m in (meals_raw.data or []):
        d = m["meal_date"]
        cal_in[d] = cal_in.get(d, 0) + (m["calories"] or 0)

    act_cal: dict[str, float] = {}
    for a in (acts_raw.data or []):
        d = a["activity_date"]
        act_cal[d] = act_cal.get(d, 0) + (a["calories"] or 0)

    iphone_cal: dict[str, int] = {}
    for h in (health_raw.data or []):
        if h.get("total_calories_iphone"):
            iphone_cal[h["health_date"]] = h["total_calories_iphone"]

    result = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        cin = round(cal_in.get(d, 0), 1)
        if d in iphone_cal:
            cout = float(iphone_cal[d])
        elif bmr:
            cout = round(bmr + act_cal.get(d, 0), 1)
        else:
            cout = round(act_cal.get(d, 0), 1)
        result.append({"date": d, "calories_in": cin, "calories_out": cout,
                        "net": round(cin - cout, 1), "goal": calorie_goal})
    return result


@router.get("/suggest-workout/{user_id}")
def suggest_workout(user_id: str, available_time: int = 45):
    db = get_supabase()
    user = db.table("user_profiles").select("*").eq("id", user_id).single().execute()
    user_profile = user.data or {}
    return suggest_exercises(user_profile, available_time)


@router.get("/user/{user_id}")
def get_user_profile(user_id: str):
    db = get_supabase()
    result = db.table("user_profiles").select("*").eq("id", user_id).single().execute()
    profile = dict(result.data or {})
    profile.pop("strava_access_token", None)
    profile.pop("strava_refresh_token", None)
    return profile


@router.put("/user/{user_id}")
def update_user_profile(user_id: str, data: dict):
    db = get_supabase()
    safe_fields = {
        "name", "age", "height_cm", "weight_kg", "goal",
        "daily_calorie_goal", "protein_goal_g", "carbs_goal_g", "fat_goal_g",
        "goal_weight_kg", "goal_weight_date", "goal_cycling_km_year",
        "goal_run_km_year", "goal_steps_day", "goals_custom",
    }
    safe_data = {k: v for k, v in data.items() if k in safe_fields and v != ""}
    result = db.table("user_profiles").update(safe_data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


@router.get("/goals/{user_id}")
def get_goals_progress(user_id: str):
    db = get_supabase()
    from datetime import datetime

    user = db.table("user_profiles").select("*").eq("id", user_id).limit(1).execute()
    profile = (user.data or [{}])[0]

    # Peso attuale (ultima rilevazione)
    latest_weight = db.table("daily_health")\
        .select("weight_kg,health_date")\
        .eq("user_id", user_id)\
        .not_.is_("weight_kg", "null")\
        .order("health_date", desc=True)\
        .limit(1).execute()
    current_weight = (latest_weight.data or [{}])[0].get("weight_kg")

    # Km bici quest'anno
    year_start = f"{date.today().year}-01-01"
    cycling = db.table("activities")\
        .select("distance_km")\
        .eq("user_id", user_id)\
        .eq("activity_type", "ride")\
        .gte("activity_date", year_start)\
        .execute()
    cycling_km_done = sum(a.get("distance_km") or 0 for a in (cycling.data or []))

    # Km corsa quest'anno
    running = db.table("activities")\
        .select("distance_km")\
        .eq("user_id", user_id)\
        .eq("activity_type", "run")\
        .gte("activity_date", year_start)\
        .execute()
    running_km_done = sum(a.get("distance_km") or 0 for a in (running.data or []))

    # Media passi (ultimi 30 giorni)
    since = (date.today() - timedelta(days=30)).isoformat()
    steps_data = db.table("daily_health")\
        .select("steps")\
        .eq("user_id", user_id)\
        .gte("health_date", since)\
        .not_.is_("steps", "null")\
        .execute()
    steps_list = [s["steps"] for s in (steps_data.data or []) if s.get("steps")]
    avg_steps = round(sum(steps_list) / len(steps_list)) if steps_list else None

    # Calcolo progressi peso
    weight_progress = None
    goal_weight = profile.get("goal_weight_kg")
    goal_date_str = profile.get("goal_weight_date")
    if goal_weight and current_weight and goal_date_str:
        goal_date = date.fromisoformat(goal_date_str)
        days_remaining = (goal_date - date.today()).days
        kg_remaining = round(current_weight - goal_weight, 1)
        starting_weight = profile.get("weight_kg") or current_weight
        total_to_lose = round(starting_weight - goal_weight, 1)
        pct = round(max(0, min(100, (1 - kg_remaining / total_to_lose) * 100)) if total_to_lose else 100, 1)
        weight_progress = {
            "current": current_weight,
            "target": goal_weight,
            "kg_remaining": kg_remaining,
            "days_remaining": days_remaining,
            "goal_date": goal_date_str,
            "percent": pct,
        }

    return {
        "weight_progress": weight_progress,
        "cycling": {
            "done_km": round(cycling_km_done, 1),
            "goal_km": profile.get("goal_cycling_km_year"),
            "percent": round(min(100, cycling_km_done / profile["goal_cycling_km_year"] * 100), 1)
                       if profile.get("goal_cycling_km_year") else None,
        },
        "running": {
            "done_km": round(running_km_done, 1),
            "goal_km": profile.get("goal_run_km_year"),
            "percent": round(min(100, running_km_done / profile["goal_run_km_year"] * 100), 1)
                       if profile.get("goal_run_km_year") else None,
        },
        "steps": {
            "avg_30d": avg_steps,
            "goal_day": profile.get("goal_steps_day"),
            "percent": round(min(100, avg_steps / profile["goal_steps_day"] * 100), 1)
                       if (avg_steps and profile.get("goal_steps_day")) else None,
        },
        "custom": profile.get("goals_custom"),
        "profile": {k: profile.get(k) for k in [
            "goal_weight_kg", "goal_weight_date", "goal_cycling_km_year",
            "goal_run_km_year", "goal_steps_day", "goals_custom",
        ]},
    }
