from datetime import date, timedelta
from backend.database.client import get_supabase
from backend.services.claude_service import generate_training_plan, adjust_training_plan


def get_active_plan(user_id: str) -> dict | None:
    db = get_supabase()
    result = db.table("training_plans")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("is_active", True)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    return result.data[0] if result.data else None


def get_plan_sessions(plan_id: str, from_date: date | None = None) -> list[dict]:
    db = get_supabase()
    query = db.table("training_sessions").select("*").eq("plan_id", plan_id)
    if from_date:
        query = query.gte("scheduled_date", from_date.isoformat())
    result = query.order("scheduled_date").execute()
    return result.data or []


def create_plan_from_claude(user_id: str, request: str, objective_id: str | None = None, target_date: str | None = None) -> dict:
    db = get_supabase()

    existing = db.table("training_plans").select("id").eq("user_id", user_id).execute()
    existing_ids = [p["id"] for p in (existing.data or [])]
    if existing_ids:
        db.table("training_sessions").delete().in_("plan_id", existing_ids).execute()
    db.table("training_plans").delete().eq("user_id", user_id).execute()

    user = db.table("user_profiles").select("*").eq("id", user_id).single().execute()
    user_profile = user.data or {}

    claude_plan = generate_training_plan(user_profile, request, target_date=target_date)

    start_date = date.today()
    duration_weeks = claude_plan.get("duration_weeks", 8)
    end_date = date.fromisoformat(target_date) if target_date else start_date + timedelta(weeks=duration_weeks)

    plan_row = {
        "user_id": user_id,
        "name": claude_plan.get("plan_name", "Piano di allenamento"),
        "goal": claude_plan.get("goal", ""),
        "description": claude_plan.get("description", ""),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "weekly_sessions": claude_plan.get("weekly_sessions", 4),
        "is_active": True,
    }
    if objective_id:
        plan_row["objective_id"] = objective_id

    plan_result = db.table("training_plans").insert(plan_row).execute()

    plan = plan_result.data[0]
    plan_id = plan["id"]

    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }

    race_date = date.fromisoformat(target_date) if target_date else None

    sessions_to_insert = []
    for s in claude_plan.get("sessions", []):
        week_num = s.get("week", 1) - 1
        day_offset = day_map.get(s.get("day_of_week", "monday"), 0)
        session_date = start_date + timedelta(weeks=week_num, days=day_offset)

        if race_date and session_date >= race_date:
            continue

        sessions_to_insert.append({
            "plan_id": plan_id,
            "user_id": user_id,
            "scheduled_date": session_date.isoformat(),
            "activity_type": s.get("activity_type", "other"),
            "title": s.get("title", "Sessione"),
            "description": s.get("description", ""),
            "duration_target_min": s.get("duration_target_min") or 0,
            "distance_target_km": s.get("distance_target_km"),
            "intensity": s.get("intensity", "moderate"),
            "status": "planned",
        })

    if sessions_to_insert:
        db.table("training_sessions").insert(sessions_to_insert).execute()

    if objective_id:
        obj_res = db.table("objectives").select("title,target_date").eq("id", objective_id).limit(1).execute()
        obj = (obj_res.data or [{}])[0]
        race_date = obj.get("target_date")
        race_title = obj.get("title") or "GARA"
        if race_date:
            db.table("training_sessions").insert({
                "plan_id": plan_id,
                "user_id": user_id,
                "scheduled_date": race_date,
                "activity_type": "race",
                "title": race_title,
                "description": "Giorno della gara",
                "duration_target_min": 0,
                "intensity": "race",
                "status": "race",
            }).execute()

    return {**plan, "sessions_created": len(sessions_to_insert), "claude_notes": claude_plan.get("notes", "")}


def adjust_plan(user_id: str, reason: str, detail: str = "", skip_days: int = 0, reduce_intensity: bool = False) -> dict:
    db = get_supabase()
    plan = get_active_plan(user_id)
    if not plan:
        return {"error": "Nessun piano attivo trovato"}

    upcoming = get_plan_sessions(plan["id"], from_date=date.today())

    plan_context = {
        "plan": plan,
        "upcoming_sessions": upcoming[:14],
        "skip_days": skip_days,
        "reduce_intensity": reduce_intensity,
    }

    adjustment_text = f"{reason}. {detail}"
    if skip_days:
        adjustment_text += f" L'utente salterà {skip_days} giorni."
    if reduce_intensity:
        adjustment_text += " L'utente vuole ridurre l'intensità."

    result = adjust_training_plan(plan_context, adjustment_text)

    applied = 0
    for change in result.get("recommended_changes", []):
        session_id = change.get("session_id")
        action = change.get("action")
        if not session_id or not action:
            continue

        update_data = {"notes": change.get("reason", "")}
        if action == "skip":
            update_data["status"] = "skipped"
        elif action == "reduce_intensity":
            update_data["intensity"] = "easy"
            update_data["description"] = change.get("new_description", "")
        elif action == "replace":
            update_data["description"] = change.get("new_description", "")

        db.table("training_sessions").update(update_data).eq("id", session_id).execute()
        applied += 1

    return {
        "assessment": result.get("assessment"),
        "motivational_message": result.get("motivational_message"),
        "changes_applied": applied,
        "overall_impact": result.get("overall_impact"),
    }
