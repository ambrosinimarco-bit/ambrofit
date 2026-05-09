"""Generazione piano allenamento settimanale con esportazione ICS e ZIP .zwo."""
import base64
import io
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from math import exp

import anthropic

from backend.config import get_settings
from backend.database.client import get_supabase
from backend.services.zwo_service import generate_zwo_xml, safe_filename

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

_DAY_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_DAY_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_MONTH_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# Pattern nomi evento comuni (esteso facilmente)
_EVENT_NAMES_RE = re.compile(
    r"(gran\s*fondo\s+[\w\s]+?(?=\s+il|\s+del|\s+a\s|\s+\d|$)|"
    r"novecolli|sportful|granfondo|medio\s*fondo\s+[\w\s]+?(?=\s+il|\s+\d|$)|"
    r"(?:gara|evento|corsa|fondista)[:\s]+([^\.,\n]+))",
    re.IGNORECASE,
)

# Formati data che Claude/utenti usano nelle note
_DATE_RE = re.compile(
    r"(?:il\s+)?(\d{1,2})\s+(" + "|".join(_MONTH_IT.keys()) + r")\s+(\d{4})"
    r"|(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
    re.IGNORECASE,
)

_DAY_MENTIONS = {
    "lunedì": "monday", "lunedi": "monday",
    "martedì": "tuesday", "martedi": "tuesday",
    "mercoledì": "wednesday", "mercoledi": "wednesday",
    "giovedì": "thursday", "giovedi": "thursday",
    "venerdì": "friday", "venerdi": "friday",
    "sabato": "saturday",
    "domenica": "sunday",
}


def _extract_event_from_notes(notes: str) -> tuple[str | None, str | None]:
    """Estrae (nome_evento, data_ISO) dalle note libere dell'utente.
    Priorità assoluta: se l'utente lo ha scritto nelle note, quella è la data giusta."""
    if not notes:
        return None, None

    event_name: str | None = None
    event_date: str | None = None

    # ── Data ──────────────────────────────────────────────────────────────────
    m = _DATE_RE.search(notes.lower())
    if m:
        if m.group(1):                         # DD mese YYYY
            day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
            month = _MONTH_IT.get(month_str.lower())
            if month:
                try:
                    event_date = date(year, month, day).isoformat()
                except ValueError:
                    pass
        else:                                   # DD/MM/YYYY
            day, month, year = int(m.group(4)), int(m.group(5)), int(m.group(6))
            try:
                event_date = date(year, month, day).isoformat()
            except ValueError:
                pass

    # ── Nome ──────────────────────────────────────────────────────────────────
    m2 = _EVENT_NAMES_RE.search(notes)
    if m2:
        raw = (m2.group(1) or m2.group(2) or "").strip()
        event_name = re.sub(r"\s+", " ", raw).title()

    return event_name or None, event_date or None


def _extract_days_from_notes(notes: str) -> list[str]:
    """Estrae i giorni disponibili dalle note (es. 'disponibile martedì e giovedì')."""
    if not notes:
        return []
    found = []
    notes_lower = notes.lower()
    for it, en in _DAY_MENTIONS.items():
        if it in notes_lower and en not in found:
            found.append(en)
    # Riordina per giorno della settimana
    return [d for d in _DAY_EN if d in found]

# ── TSB helpers ──────────────────────────────────────────────────────────────

def _estimate_tss(a: dict, ftp: int) -> float:
    if a.get("normalized_power_w") and a.get("duration_min"):
        np_ = float(a["normalized_power_w"])
        dur_h = float(a["duration_min"]) / 60
        return round((np_ / ftp) ** 2 * dur_h * 100, 1)
    if a.get("avg_power_w") and a.get("duration_min"):
        p = float(a["avg_power_w"])
        dur_h = float(a["duration_min"]) / 60
        return round((p / ftp) ** 2 * dur_h * 100, 1)
    if a.get("avg_heart_rate") and a.get("duration_min"):
        hr = float(a["avg_heart_rate"])
        hr_rest, thr_hr, hr_max = 50, 155, 182
        trimp = float(a["duration_min"]) * (hr - hr_rest) / (thr_hr - hr_rest) * 0.64 * exp(
            1.92 * (hr - hr_rest) / (hr_max - hr_rest)
        )
        return round(trimp, 1)
    return round(float(a.get("duration_min") or 0) * 0.5, 1)


def _calc_fitness(activities: list[dict], ftp: int) -> tuple[float, float, float]:
    tss_by_day: dict[str, float] = {}
    for a in activities:
        d = a.get("activity_date") or ""
        if d:
            tss_by_day[d] = tss_by_day.get(d, 0) + _estimate_tss(a, ftp)

    k_ctl = 1 - exp(-1 / 42)
    k_atl = 1 - exp(-1 / 7)
    ctl = atl = 0.0
    today = date.today()
    for i in range(90, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        tss = tss_by_day.get(d, 0.0)
        ctl = ctl + k_ctl * (tss - ctl)
        atl = atl + k_atl * (tss - atl)
    return round(ctl, 1), round(atl, 1), round(ctl - atl, 1)


# ── ICS generation ───────────────────────────────────────────────────────────

def _ics_fold(line: str) -> str:
    if len(line.encode("utf-8")) <= 75:
        return line
    result = []
    while len(line.encode("utf-8")) > 75:
        # Safe fold: split at byte boundary
        chunk = line[:75]
        result.append(chunk)
        line = " " + line[75:]
    result.append(line)
    return "\r\n".join(result)


def _ics_esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def generate_ics(sessions: list[dict], ftp: int = 202) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ambrofit//Training Plan//IT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Ambrofit Piano Allenamenti",
        "X-WR-TIMEZONE:Europe/Rome",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for s in sessions:
        if s.get("type") == "rest" or not s.get("date"):
            continue
        try:
            sd = date.fromisoformat(s["date"])
        except ValueError:
            continue

        start_h = int(s.get("start_hour", 7))
        dur_min = int(s.get("duration_min") or 60)
        dt_start = datetime(sd.year, sd.month, sd.day, start_h, 0)
        dt_end = dt_start + timedelta(minutes=dur_min)

        # Build description
        desc_parts = [s.get("description") or ""]
        pt = s.get("power_targets") or {}
        if pt.get("main"):
            desc_parts.append(f"Potenza target: ~{pt['main']}W")
        segs = s.get("segments") or []
        struct = []
        for seg in segs:
            t = seg.get("type", "")
            if t == "Warmup":
                struct.append(f"Riscaldamento {seg.get('duration_min',0)}min")
            elif t == "Cooldown":
                struct.append(f"Defaticamento {seg.get('duration_min',0)}min")
            elif t == "SteadyState":
                struct.append(f"Steady {seg.get('duration_min',0)}min@{round(float(seg.get('power',0.7))*ftp)}W")
            elif t == "IntervalsT":
                struct.append(
                    f"{seg.get('repeat',4)}x{seg.get('on_duration_min',1)}min"
                    f"@{round(float(seg.get('on_power',1.0))*ftp)}W"
                    f"/{seg.get('off_duration_min',1)}min"
                    f"@{round(float(seg.get('off_power',0.55))*ftp)}W"
                )
        if struct:
            desc_parts.append("Struttura: " + " | ".join(struct))
        desc_parts.append("Apri Ambrofit per file .zwo e dettagli completi.")
        description = _ics_esc(" | ".join(p for p in desc_parts if p))

        name = s.get("name") or "Allenamento"
        uid = str(uuid.uuid4()) + "@ambrofit"

        lines += [
            "BEGIN:VEVENT",
            _ics_fold(f"UID:{uid}"),
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID=Europe/Rome:{dt_start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Europe/Rome:{dt_end.strftime('%Y%m%dT%H%M%S')}",
            _ics_fold(f"SUMMARY:{_ics_esc('🚴 ' + name)}"),
            _ics_fold(f"DESCRIPTION:{description}"),
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Allenamento tra 30 minuti",
            "TRIGGER:-PT30M",
            "END:VALARM",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ── ZIP of .zwo files ────────────────────────────────────────────────────────

def generate_zwos_zip(sessions: list[dict], ftp: int) -> str:
    """Ritorna ZIP in base64 con tutti i file .zwo delle sessioni indoor."""
    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for s in sessions:
            segs = s.get("segments")
            if not segs:
                continue
            workout = {
                "name": s.get("name", "Workout"),
                "description": s.get("description", ""),
                "segments": segs,
            }
            xml = generate_zwo_xml(workout, ftp)
            day = (s.get("day_name") or "giorno").replace(" ", "_")
            fname = safe_filename(f"{day}_{s.get('name', 'workout')}") + ".zwo"
            zf.writestr(fname, xml.encode("utf-8"))
            added += 1

    if not added:
        return ""
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


# ── Period helpers ────────────────────────────────────────────────────────────

def _get_period_dates(period: str) -> tuple[date, date]:
    today = date.today()
    mon = today - timedelta(days=today.weekday())
    if period == "next_week":
        start = mon + timedelta(days=7)
    else:
        start = mon
    end = start + timedelta(days=13 if period == "two_weeks" else 6)
    return start, end


# ── Post-processing: enforce hard constraints in Python ───────────────────────

_RIDE_TYPES = {"base", "long", "sweetspot", "tempo", "vo2max", "recovery"}
_WEEKEND = {"saturday", "sunday"}


def _post_process_sessions(
    sessions: list[dict],
    available_days: list[str] | None,
    post_long_date: str | None,
) -> list[dict]:
    """Enforce hard constraints after Claude generates the plan."""
    for s in sessions:
        date_str = s.get("date", "")
        try:
            d = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            continue

        day_en = _DAY_EN[d.weekday()]

        # 1. Available days: non-allowed days become rest
        if available_days and day_en not in available_days:
            s["type"] = "rest"
            s["name"] = "Riposo"
            s["description"] = ""
            s["segments"] = None
            s["exercises"] = None
            s["duration_min"] = 0
            continue

        if s.get("type") == "rest":
            continue

        # 2. Post-long recovery: day after 3+ hour activity = forced recovery
        if post_long_date and date_str == post_long_date:
            if s.get("type") not in ("rest", "recovery"):
                s["type"] = "recovery"
                s["name"] = "Recupero attivo"
                s["description"] = "Recupero obbligatorio dopo uscita lunga."
                s["segments"] = None
                s["duration_min"] = min(int(s.get("duration_min") or 45), 45)
            continue

        # 3. Weekday rides capped at 90 min
        if day_en not in _WEEKEND and s.get("type") in _RIDE_TYPES:
            if int(s.get("duration_min") or 0) > 90:
                s["duration_min"] = 90
                segs = s.get("segments")
                if segs:
                    total = sum(int(seg.get("duration_min") or 0) for seg in segs)
                    if total > 90:
                        scale = 90 / total
                        for seg in segs:
                            seg["duration_min"] = max(1, round(int(seg.get("duration_min") or 1) * scale))

    return sessions


# ── Main entry point ─────────────────────────────────────────────────────────

def generate_weekly_plan(
    user_id: str,
    period: str = "current_week",
    objective: str = "base aerobica",
    available_days: list[str] | None = None,
    target_event_name: str | None = None,
    target_event_date: str | None = None,
    user_notes: str | None = None,
) -> dict:
    db = get_supabase()

    # Profile
    profile = (db.table("user_profiles").select("*").eq("id", user_id).limit(1).execute().data or [{}])[0]
    ftp = int(profile.get("ftp_watts") or 202)
    weight_kg = float(profile.get("weight_kg") or 75.0)
    medical = profile.get("medical_notes") or "nessuno"
    coaching = profile.get("coaching_notes") or "ciclista endurance 53 anni, 2-3 sessioni/settimana"

    # Recent activities for TSB
    today = date.today()
    since_90 = (today - timedelta(days=90)).isoformat()
    acts = db.table("activities").select(
        "activity_date,duration_min,avg_power_w,normalized_power_w,avg_heart_rate"
    ).eq("user_id", user_id).gte("activity_date", since_90).execute().data or []
    ctl, atl, tsb = _calc_fitness(acts, ftp)

    # Extract event/days from free-text notes (priority over UI fields) — Python handles this
    if user_notes:
        extracted_name, extracted_date = _extract_event_from_notes(user_notes)
        if not target_event_name:
            target_event_name = extracted_name
        if not target_event_date:
            target_event_date = extracted_date
        if not available_days:
            available_days = _extract_days_from_notes(user_notes) or None

    # Detect post-long-ride day to enforce in post-processing
    post_long_date: str | None = None
    since_2days = (today - timedelta(days=2)).isoformat()
    recent_acts = db.table("activities").select("activity_date,duration_min")\
        .eq("user_id", user_id).gte("activity_date", since_2days).execute().data or []
    for a in recent_acts:
        if float(a.get("duration_min") or 0) >= 180:
            act_date = a.get("activity_date", "")
            if act_date == today.isoformat():
                post_long_date = (today + timedelta(days=1)).isoformat()
            elif act_date == (today - timedelta(days=1)).isoformat():
                post_long_date = today.isoformat()
            break

    # Period
    start_date, end_date = _get_period_dates(period)

    # Build date list for Claude
    date_list, d = [], start_date
    while d <= end_date:
        date_list.append(f"{_DAY_IT[d.weekday()]} {d.isoformat()}")
        d += timedelta(days=1)

    target_block = (
        f"\nEvento target: \"{target_event_name}\" il {target_event_date} "
        "(calibra il carico per arrivare riposato)."
        if target_event_name and target_event_date else ""
    )
    notes_block = f"\nNote aggiuntive: {user_notes}" if user_notes and user_notes.strip() else ""

    # ── Chiamata 1: genera il piano (struttura + segmenti ZWO, senza esercizi) ──
    prompt = f"""Genera un piano settimanale di allenamento per un ciclista in formato JSON.

PERIODO: {start_date} → {end_date}
Giorni: {", ".join(date_list)}
Obiettivo: {objective}
FTP {ftp}W | CTL {ctl} | ATL {atl} | TSB {tsb}
Contesto atleta: {coaching}{target_block}{notes_block}

Zone FTP: Z1=0.50-0.56 | Z2=0.56-0.75 | SS=0.84-0.95 | Tempo=0.76-0.90 | VO2max=1.06-1.20

JSON (un elemento per ogni giorno del periodo):
{{
  "sessions": [
    {{
      "day_name": "lunedì",
      "date": "YYYY-MM-DD",
      "type": "recovery|base|long|sweetspot|tempo|vo2max|strength|mobility|rest",
      "name": "Sweet Spot 45min",
      "duration_min": 45,
      "indoor": true,
      "description": "1-2 frasi obiettivo",
      "power_targets": {{"main": 178, "zone": "Z3-Z4"}},
      "segments": [
        {{"type":"Warmup","duration_min":10,"power_low":0.50,"power_high":0.75}},
        {{"type":"SteadyState","duration_min":28,"power":0.88}},
        {{"type":"Cooldown","duration_min":7,"power_high":0.60,"power_low":0.35}}
      ],
      "exercises": null
    }}
  ],
  "summary": "Logica del piano (2-3 frasi)"
}}

Sessioni indoor: includi segments (Warmup + corpo + Cooldown).
Sessioni outdoor e strength/mobility: segments=null, exercises=null."""

    resp1 = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw1 = resp1.content[0].text.strip()
    if raw1.startswith("```"):
        raw1 = raw1.split("```", 2)[1]
        if raw1.startswith("json"):
            raw1 = raw1[4:]
        raw1 = raw1.rstrip("`").strip()
    plan_data = json.loads(raw1)
    sessions = plan_data.get("sessions", [])
    summary = plan_data.get("summary", "")

    # ── Post-processing: enforce hard constraints deterministically ──────────
    sessions = _post_process_sessions(sessions, available_days or None, post_long_date)

    # ── Chiamata 2: esercizi per sessioni strength/mobility ──────────────────
    sm_indices = [(i, s) for i, s in enumerate(sessions)
                  if s.get("type") in ("strength", "mobility")]
    if sm_indices:
        sessions_desc = "\n".join(
            f'{fi}. [{s["type"].upper()}] "{s.get("name","")}" {s.get("duration_min",40)}min — {s.get("description","")}'
            for fi, (_, s) in enumerate(sm_indices)
        )
        prompt2 = f"""Genera esercizi dettagliati per queste sessioni di forza/mobilità.

SESSIONI:
{sessions_desc}

ATTREZZATURA: TRX, bosu, tappetino, elastici, manubri leggeri/medi, panca.
VINCOLI MEDICI (inderogabili):
- NO pressione zona inguinale (no leg press, no squat profondi con carico)
- NO addominali massimali (no crunch pesanti, no sit-up)
- Focus: glutei, quadricipiti, dorsali, spalle, core stabilità
Contesto: {coaching} | {medical}

strength → 7-8 esercizi forza/stabilità funzionale ciclismo.
mobility → 7-8 esercizi stretching/mobilità articolare post-bici.
description: 1 frase concisa. notes: 1 indicazione tecnica breve.

JSON:
{{
  "sessions": [
    {{
      "index": 0,
      "exercises": [
        {{"name":"TRX Row","equipment":"TRX","description":"Tira le maniglie verso il petto a corpo rigido.","sets_reps":"3×12","rest_sec":60,"notes":"Gomiti vicini al busto."}}
      ]
    }}
  ]
}}"""

        resp2 = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt2}],
        )
        raw2 = resp2.content[0].text.strip()
        if raw2.startswith("```"):
            raw2 = raw2.split("```", 2)[1]
            if raw2.startswith("json"):
                raw2 = raw2[4:]
            raw2 = raw2.rstrip("`").strip()
        ex_data = json.loads(raw2)
        for entry in ex_data.get("sessions", []):
            fill_idx = entry.get("index", 0)
            if fill_idx < len(sm_indices):
                orig_idx, _ = sm_indices[fill_idx]
                sessions[orig_idx]["exercises"] = entry.get("exercises") or []

    ics_content = generate_ics(sessions, ftp)
    zwo_zip_b64 = generate_zwos_zip(sessions, ftp)
    indoor_count = sum(1 for s in sessions if s.get("segments"))

    return {
        "sessions": sessions,
        "ics_content": ics_content,
        "zwo_zip_b64": zwo_zip_b64,
        "zwo_count": indoor_count,
        "summary": summary,
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "metrics": {"ctl": ctl, "atl": atl, "tsb": tsb},
    }
