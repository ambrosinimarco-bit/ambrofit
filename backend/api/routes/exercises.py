from fastapi import APIRouter, HTTPException
from backend.database.client import get_supabase

router = APIRouter(prefix="/api/exercises", tags=["exercises"])


@router.get("/")
def list_routines(user_id: str):
    """Lista tutte le routine con i loro esercizi."""
    db = get_supabase()
    routines_res = db.table("exercise_routines").select("*")\
        .eq("user_id", user_id)\
        .eq("is_active", True)\
        .order("sort_order").order("created_at").execute()
    routines = routines_res.data or []

    if not routines:
        return []

    # Fetch tutti gli esercizi per le routine trovate
    routine_ids = [r["id"] for r in routines]
    exercises_res = db.table("exercises").select("*")\
        .in_("routine_id", routine_ids)\
        .order("position").order("created_at").execute()
    exercises = exercises_res.data or []

    # Raggruppa esercizi per routine
    exercises_by_routine: dict = {}
    for ex in exercises:
        rid = ex["routine_id"]
        if rid not in exercises_by_routine:
            exercises_by_routine[rid] = []
        exercises_by_routine[rid].append(ex)

    for r in routines:
        r["exercises"] = exercises_by_routine.get(r["id"], [])

    return routines


@router.post("/routines")
def create_routine(data: dict):
    """Crea una nuova routine."""
    db = get_supabase()
    payload = {
        "user_id": data["user_id"],
        "name": data["name"],
        "type": data.get("type", "strength"),
        "description": data.get("description"),
        "is_active": True,
        "sort_order": data.get("sort_order", 0),
    }
    result = db.table("exercise_routines").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio della routine")
    return result.data[0]


@router.put("/routines/{routine_id}")
def update_routine(routine_id: str, data: dict):
    """Aggiorna una routine esistente."""
    db = get_supabase()
    safe_fields = {"name", "type", "description", "is_active", "sort_order"}
    update_data = {k: v for k, v in data.items() if k in safe_fields}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nessun campo valido da aggiornare")
    result = db.table("exercise_routines").update(update_data).eq("id", routine_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Routine non trovata")
    return result.data[0]


@router.delete("/routines/{routine_id}")
def delete_routine(routine_id: str):
    """Elimina una routine (cascade elimina gli esercizi)."""
    db = get_supabase()
    db.table("exercise_routines").delete().eq("id", routine_id).execute()
    return {"ok": True}


@router.post("/")
def create_exercise(data: dict):
    """Crea un nuovo esercizio in una routine."""
    db = get_supabase()
    payload = {
        "routine_id": data["routine_id"],
        "user_id": data["user_id"],
        "name": data["name"],
        "sets": data.get("sets"),
        "reps": data.get("reps"),
        "rest_seconds": data.get("rest_seconds"),
        "notes": data.get("notes"),
        "position": data.get("position", 0),
    }
    result = db.table("exercises").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio dell'esercizio")
    return result.data[0]


@router.put("/{exercise_id}")
def update_exercise(exercise_id: str, data: dict):
    """Aggiorna un esercizio esistente."""
    db = get_supabase()
    safe_fields = {"name", "sets", "reps", "rest_seconds", "notes", "position"}
    update_data = {k: v for k, v in data.items() if k in safe_fields}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nessun campo valido da aggiornare")
    result = db.table("exercises").update(update_data).eq("id", exercise_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Esercizio non trovato")
    return result.data[0]


@router.delete("/{exercise_id}")
def delete_exercise(exercise_id: str):
    """Elimina un esercizio."""
    db = get_supabase()
    db.table("exercises").delete().eq("id", exercise_id).execute()
    return {"ok": True}
