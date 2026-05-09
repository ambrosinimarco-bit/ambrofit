"""Generazione piano allenamento settimanale con esportazione ICS e ZIP .zwo."""
import base64
import io
import json
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
                struct.append(f"Riscaldamento {seg['duration_min']}min")
            elif t == "Cooldown":
                struct.append(f"Defaticamento {seg['duration_min']}min")
            elif t == "SteadyState":
                struct.append(f"Steady {seg['duration_min']}min@{round(float(seg['power'])*ftp)}W")
            elif t == "IntervalsT":
                struct.append(
                    f"{seg['repeat']}x{seg['on_duration_min']}min@{round(float(seg['on_power'])*ftp)}W"
                    f"/{seg['off_duration_min']}min@{round(float(seg['off_power'])*ftp)}W"
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
    since_90 = (date.today() - timedelta(days=90)).isoformat()
    acts = db.table("activities").select(
        "activity_date,duration_min,avg_power_w,normalized_power_w,avg_heart_rate"
    ).eq("user_id", user_id).gte("activity_date", since_90).execute().data or []
    ctl, atl, tsb = _calc_fitness(acts, ftp)

    # Period
    start_date, end_date = _get_period_dates(period)

    # Available days → Italian labels
    if available_days:
        avail_it = [_DAY_IT[_DAY_EN.index(d)] for d in available_days if d in _DAY_EN]
    else:
        avail_it = _DAY_IT

    # Build date list
    date_list, d = [], start_date
    while d <= end_date:
        date_list.append(f"{_DAY_IT[d.weekday()]} {d.isoformat()}")
        d += timedelta(days=1)

    user_notes_block = (
        f"\n⚠️ ISTRUZIONI PRIORITARIE DELL'UTENTE (sovrascrivono ogni altra regola):\n{user_notes}\n"
        if user_notes and user_notes.strip() else ""
    )

    target_block = ""
    if target_event_name and target_event_date:
        target_block = (
            f"\n⚠️ EVENTO TARGET: \"{target_event_name}\" il {target_event_date}\n"
            "CRITICO: usa ESATTAMENTE questa data nel tuo ragionamento — non modificarla né ricalcolarla.\n"
            "Gestisci il carico in modo da arrivare all'evento con TSB positivo (+5/+15).\n"
        )

    prompt = f"""Crea un piano di allenamento ciclismo dettagliato per Marco.
{user_notes_block}
PERIODO: {start_date} → {end_date}
Giorni del periodo: {", ".join(date_list)}
Obiettivo settimana: {objective}
Giorni disponibili per allenarsi: {", ".join(avail_it)}{target_block}
PROFILO:
FTP {ftp}W | Peso {weight_kg}kg
CTL {ctl} | ATL {atl} | TSB {tsb}
Vincoli medici: {medical}
Contesto: {coaching}

Zone FTP: Z1=0.50-0.56 | Z2=0.56-0.75 | SS=0.84-0.95 | Tempo=0.76-0.90 | VO2max=1.06-1.20

SESSIONI DI FORZA/MOBILITÀ (type="strength" o type="mobility"):
- Per queste sessioni: segments=null, indoor=true, power_targets=null.
- Aggiungi campo "exercises" con lista dettagliata degli esercizi.
- Attrezzatura disponibile: TRX, bosu, tappetino, elastici (varie resistenze), manubri leggeri/medi, panca.
- VINCOLI MEDICI ESERCIZI (CRITICO, inderogabili):
  * NO pressione diretta zona inguinale (no leg press pesante, no squat profondi con carico)
  * NO addominali massimali (no crunch pesanti, no sit-up, no leg raise pesanti)
  * Preferire esercizi in piedi, TRX, o plank leggeri
  * Focus funzionale ciclismo: glutei, quadricipiti, dorsali, spalle, core stabilità
- Formato campo "exercises":
  [
    {{
      "name": "TRX Row",
      "equipment": "TRX",
      "description": "Inclinati con i piedi avanti verso il punto di ancoraggio. Tira le maniglie verso il petto flettendo i gomiti, tenendo il corpo rigido.",
      "sets_reps": "3×12",
      "rest_sec": 60,
      "notes": "Core attivo. Gomiti vicini al busto. Evita di inarcare la schiena."
    }}
  ]
- Per "strength": 6-10 esercizi focalizzati su forza e stabilità per il ciclismo.
- Per "mobility": 6-10 esercizi di allungamento, mobilità articolare, rilassamento muscolare post-bici.

LIMITI DURATA (rispettare rigorosamente):
- Sessioni infrasettimanali lun-ven: MAX 75 min oppure MAX 40km outdoor. Di norma indoor sui rulli.
- Solo il lungo del weekend (sab o dom): può essere outdoor, 90-180 min, 60-100km.
- Sessioni di recupero: MAX 45-60 min.
- Se una sessione è indoor non inserire distanza (solo duration_min).
- NON assegnare mai >40km in un giorno infrasettimanale. Mai >90 min infrasettimanale.

REGOLE GENERALI:
- Genera una voce per OGNI giorno del periodo (anche i giorni di riposo: type="rest", segments=null)
- Sessioni indoor hanno segments per il file .zwo (Warmup + corpo + Cooldown)
- Sessioni outdoor: indoor=false, segments=null
- TSB<-10 → privilegia recupero/Z2. TSB>+10 → c'è spazio per qualità. TSB 0-10 → mix equilibrato.
- Rispetta vincoli medici. Riscaldamento sempre ≥8min.

JSON esatto:
{{
  "sessions": [
    {{
      "day_name": "lunedì",
      "date": "YYYY-MM-DD",
      "type": "recovery|base|long|sweetspot|tempo|vo2max|strength|mobility|rest",
      "name": "Sweet Spot 45min",
      "duration_min": 45,
      "indoor": true,
      "description": "Obiettivo e istruzioni (2-3 frasi concrete)",
      "power_targets": {{"main": 178, "zone": "Z3-Z4"}},
      "segments": [
        {{"type":"Warmup","duration_min":10,"power_low":0.50,"power_high":0.75}},
        {{"type":"SteadyState","duration_min":28,"power":0.88}},
        {{"type":"Cooldown","duration_min":7,"power_high":0.60,"power_low":0.35}}
      ],
      "exercises": null
    }},
    {{
      "day_name": "mercoledì",
      "date": "YYYY-MM-DD",
      "type": "strength",
      "name": "Forza funzionale 40min",
      "duration_min": 40,
      "indoor": true,
      "description": "Circuito forza funzionale per il ciclismo. Focus glutei e dorsali.",
      "power_targets": null,
      "segments": null,
      "exercises": [
        {{"name":"TRX Row","equipment":"TRX","description":"Tira le maniglie verso il petto, corpo rigido.","sets_reps":"3×12","rest_sec":60,"notes":"Gomiti vicini al busto."}},
        {{"name":"Romanian Deadlift","equipment":"manubri","description":"Piedi larghezza spalle, scendi con manubri lungo le gambe mantenendo schiena dritta.","sets_reps":"3×10","rest_sec":90,"notes":"Senti lo stretch ai femorali. Nessuna pressione inguinale."}}
      ]
    }}
  ],
  "summary": "Logica del piano (3-4 frasi)"
}}"""

    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rstrip("`").strip()
    plan_data = json.loads(raw)
    sessions = plan_data.get("sessions", [])
    summary = plan_data.get("summary", "")

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
