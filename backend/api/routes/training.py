import asyncio
import json
import logging
import traceback
import uuid
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
from pydantic import BaseModel
from backend.database.client import get_supabase
from backend.database.models import PlanAdjustmentRequest
from backend.services.training_plan_service import (
    get_active_plan,
    get_plan_sessions,
    adjust_plan,
    create_plan_from_claude,
)

router = APIRouter(prefix="/api/training", tags=["training"])


# ── Plan creation / CRUD ─────────────────────────────────────────────────────

class CreatePlanRequest(BaseModel):
    objective_id: str | None = None
    weekly_sessions: int = 4
    disciplines: list[str] = ["ride"]
    notes: str | None = None
    target_date: str | None = None


@router.post("/plan/{user_id}")
def create_plan(user_id: str, body: CreatePlanRequest):
    db = get_supabase()

    objective_title: str | None = None
    effective_target_date = body.target_date

    if body.objective_id:
        obj_res = db.table("objectives").select("title,target_date")\
            .eq("id", body.objective_id).limit(1).execute()
        if obj_res.data:
            obj = obj_res.data[0]
            objective_title = obj.get("title")
            if not effective_target_date:
                effective_target_date = obj.get("target_date")

    parts = [
        f"Sessioni settimanali: {body.weekly_sessions}",
        f"Discipline: {', '.join(body.disciplines)}",
    ]
    if objective_title:
        parts.append(f"Obiettivo principale: {objective_title}")
    if effective_target_date:
        parts.append(f"Data evento target: {effective_target_date}")
    if body.notes:
        parts.append(f"Preferenze utente: {body.notes}")

    request_str = ". ".join(parts) + "."

    db.table("training_sessions").delete().eq("user_id", user_id).execute()

    result = create_plan_from_claude(user_id, request_str, objective_id=body.objective_id)
    return result


@router.get("/plan/{user_id}")
def get_plan(user_id: str):
    plan = get_active_plan(user_id)
    if not plan:
        return {"plan": None, "sessions": []}
    sessions = get_plan_sessions(plan["id"])
    return {"plan": plan, "sessions": sessions}


@router.post("/plan/{user_id}/adjust")
def adjust_plan_endpoint(user_id: str, adjustment: PlanAdjustmentRequest):
    return adjust_plan(
        user_id,
        adjustment.reason,
        adjustment.detail or "",
        adjustment.skip_days or 0,
        adjustment.reduce_intensity or False,
    )


@router.patch("/session/{session_id}")
def update_session(session_id: str, data: dict):
    db = get_supabase()
    allowed = {"status", "notes", "description", "intensity", "duration_target_min"}
    safe_data = {k: v for k, v in data.items() if k in allowed}
    result = db.table("training_sessions").update(safe_data).eq("id", session_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    return result.data[0]


@router.get("/sessions/{user_id}")
def get_sessions(user_id: str, from_date: date | None = None, days: int = 14):
    db = get_supabase()
    start = (from_date or date.today()).isoformat()
    end = ((from_date or date.today()) + timedelta(days=days)).isoformat()
    result = db.table("training_sessions")\
        .select("*")\
        .eq("user_id", user_id)\
        .gte("scheduled_date", start)\
        .lte("scheduled_date", end)\
        .order("scheduled_date")\
        .execute()
    return result.data or []


# ── ICS generation from plain-text plan ──────────────────────────────────────

class ICSRequest(BaseModel):
    user_id: str
    plan_text: str
    week_start: str  # YYYY-MM-DD


def _ics_esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _build_ics(sessions: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ambrofit//Training Plan//IT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Ambrofit Allenamenti",
        "X-WR-TIMEZONE:Europe/Rome",
    ]
    for s in sessions:
        try:
            d = date.fromisoformat(s["date"])
        except (ValueError, KeyError):
            continue
        start_h = int(s.get("start_hour") or 7)
        dur = int(s.get("duration_min") or 90)
        dt_start = datetime(d.year, d.month, d.day, start_h, 0)
        dt_end = dt_start + timedelta(minutes=dur)
        title = _ics_esc("🚴 " + (s.get("title") or "Allenamento"))
        desc = _ics_esc(s.get("description") or "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}@ambrofit",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID=Europe/Rome:{dt_start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Europe/Rome:{dt_end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{title}",
            f"DESCRIPTION:{desc}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Allenamento tra 30 minuti",
            "TRIGGER:-PT30M",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@router.post("/generate-ics")
async def generate_ics_endpoint(body: ICSRequest):
    """Claude reads the plain-text plan and extracts sessions; returns .ics content."""
    import anthropic
    from backend.config import get_settings
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    prompt = f"""Leggi questo piano di allenamento e restituisci un JSON array con le sessioni.
Settimana che inizia il: {body.week_start}

PIANO:
{body.plan_text}

Per ogni giorno con una sessione di allenamento (NON i giorni di riposo) restituisci:
- "date": data ISO YYYY-MM-DD (calcola le date reali a partire dal {body.week_start})
- "title": titolo breve (es. "Uscita base Z2", "Sweet Spot 60min", "Forza")
- "description": testo descrittivo completo copiato dal piano
- "duration_min": durata in minuti ("1h30" → 90, "2 ore" → 120, default 90)
- "start_hour": ora di inizio (7 se non specificata)

Rispondi SOLO con il JSON array, nessun altro testo."""

    try:
        resp = await asyncio.to_thread(
            client.messages.create,
            model="claude-opus-4-7",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rstrip("`").strip()
        sessions = json.loads(raw)
    except Exception as e:
        logger.error("generate-ics ERROR:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    ics = _build_ics(sessions)
    logger.info("generate-ics: %d sessioni per settimana %s", len(sessions), body.week_start)
    return {"ics_content": ics, "session_count": len(sessions)}


# ── ZWO generation ────────────────────────────────────────────────────────────

class ZwoGenerateRequest(BaseModel):
    user_id: str
    session_type: str   # recovery | base | sweetspot | tempo | vo2max
    duration_min: int


_SESSION_LABELS = {
    "recovery":  "recupero Z1",
    "base":      "base endurance Z2",
    "sweetspot": "sweet spot",
    "tempo":     "tempo",
    "vo2max":    "VO2max intervalli",
}


@router.post("/generate-zwo")
async def generate_zwo_endpoint(body: ZwoGenerateRequest):
    """Genera un file .zwo per MyWhoosh."""
    db = get_supabase()
    profile_res = db.table("user_profiles").select("ftp_watts,weight_kg")\
        .eq("id", body.user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]
    ftp = profile.get("ftp_watts") or 202
    weight_kg = float(profile.get("weight_kg") or 75.0)

    label = _SESSION_LABELS.get(body.session_type, body.session_type)
    request_text = f"sessione {label} da {body.duration_min} minuti"

    from backend.services.claude_service import plan_zwo_workout
    from backend.services.zwo_service import generate_zwo_xml, safe_filename

    try:
        workout = await asyncio.to_thread(plan_zwo_workout, request_text, ftp)
        xml_content = generate_zwo_xml(workout, ftp, weight_kg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    filename = safe_filename(workout.get("name", "Workout")) + ".zwo"
    return {"xml": xml_content, "filename": filename, "workout": workout}
