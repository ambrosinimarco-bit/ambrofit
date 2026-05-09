"""Coach service con memoria contestuale completa (30gg) e sessioni conversazionali."""
import anthropic
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from backend.config import get_settings
from backend.database.client import get_supabase

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# ── Sessioni in memoria (max 2 ore di continuità) ──────────────────────────────

SESSION_TIMEOUT = timedelta(hours=2)
# user_id -> [{"role": "user"|"assistant", "content": str, "ts": datetime}]
_sessions: dict[str, list[dict]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_active_session(user_id: str) -> list[dict]:
    """Ritorna la sessione attiva; la azzera se scaduta (>2 ore dall'ultimo msg)."""
    history = _sessions.get(user_id, [])
    if history and (_now() - history[-1]["ts"]) > SESSION_TIMEOUT:
        history = []
        _sessions[user_id] = history
    return history


def _save_exchange(user_id: str, user_msg: str, assistant_msg: str) -> None:
    history = _sessions.setdefault(user_id, [])
    now = _now()
    history.append({"role": "user",      "content": user_msg,      "ts": now})
    history.append({"role": "assistant", "content": assistant_msg, "ts": now})
    if len(history) > 40:  # max 20 scambi
        _sessions[user_id] = history[-40:]


# ── Costruzione sezioni contesto ───────────────────────────────────────────────

def _weekly_loads(activities: list) -> str:
    weeks: dict = defaultdict(lambda: {"n": 0, "min": 0.0, "km": 0.0})
    for a in activities:
        try:
            d = date.fromisoformat(a.get("activity_date") or date.today().isoformat())
        except ValueError:
            continue
        mon = d - timedelta(days=d.weekday())
        w = weeks[mon]
        w["n"] += 1
        w["min"] += float(a.get("duration_min") or 0)
        w["km"] += float(a.get("distance_km") or 0)

    if not weeks:
        return "Nessuna attività."

    lines = []
    for mon in sorted(weeks.keys(), reverse=True):
        w = weeks[mon]
        sun = mon + timedelta(days=6)
        h, m = divmod(int(w["min"]), 60)
        dur = f"{h}h{m:02d}'" if h else f"{m}'"
        km_part = f" | {w['km']:.0f}km" if w["km"] else ""
        lines.append(f"• {mon.strftime('%d %b')}–{sun.strftime('%d %b')}: {w['n']} sessioni | {dur}{km_part}")
    return "\n".join(lines)


def _fmt_activities(activities: list) -> str:
    if not activities:
        return "Nessuna attività nei 30 giorni."
    lines = []
    for a in activities:
        name = a.get("name") or "Attività"
        atype = a.get("activity_type") or "altro"
        line = f"• {a.get('activity_date')} — {name} ({atype})"
        details = []
        dur = a.get("duration_min")
        if dur:
            h, m = divmod(int(float(dur)), 60)
            details.append(f"{h}h{m:02d}'" if h else f"{m}'")
        if a.get("distance_km"):
            details.append(f"{a['distance_km']}km")
        if a.get("elevation_m"):
            details.append(f"+{a['elevation_m']}m")
        if a.get("avg_heart_rate"):
            details.append(f"FC {a['avg_heart_rate']}bpm")
        if a.get("max_heart_rate"):
            details.append(f"FCmax {a['max_heart_rate']}bpm")
        if a.get("rpe"):
            details.append(f"RPE {a['rpe']}/10")
        if details:
            line += f" [{' | '.join(details)}]"
        if a.get("physical_notes"):
            line += f"\n  ⚠ {a['physical_notes']}"
        lines.append(line)
    return "\n".join(lines)


def _fmt_checkins(activities: list) -> str:
    """Ultime 10 sessioni con check-in (RPE o note fisiche)."""
    with_checkin = [
        a for a in activities
        if a.get("check_in_done") or a.get("rpe") or a.get("physical_notes")
    ]
    with_checkin.sort(key=lambda a: a.get("activity_date") or "", reverse=True)
    recent = with_checkin[:10]
    if not recent:
        return "Nessun check-in registrato negli ultimi 30 giorni."
    lines = []
    for a in recent:
        line = f"• {a.get('activity_date')} — {a.get('name') or 'Attività'}"
        if a.get("rpe"):
            line += f": RPE {a['rpe']}/10"
        if a.get("physical_notes"):
            line += f" — \"{a['physical_notes']}\""
        lines.append(line)
    return "\n".join(lines)


def _fmt_nutrition(meals_by_day: dict, health_by_day: dict) -> str:
    if not meals_by_day:
        return "Nessun dato nutrizionale disponibile."

    header = "Data        | KcalIn | KcalOut | Bilancio | Prot  | Carbs | Grassi"
    rows = [header, "-" * len(header)]
    tot_kcal = tot_prot = tot_carbs = tot_fat = 0.0
    n = 0

    for day in sorted(meals_by_day.keys(), reverse=True):
        meals = meals_by_day[day]
        ki = sum(m.get("calories", 0) or 0 for m in meals)
        p  = sum(m.get("protein_g", 0) or 0 for m in meals)
        c  = sum(m.get("carbs_g", 0) or 0 for m in meals)
        f  = sum(m.get("fat_g", 0) or 0 for m in meals)
        ko = (health_by_day.get(day) or {}).get("total_calories_iphone") or 0
        bal = f"{int(ki - ko):+d}" if ko else "n/d"
        ko_s = str(int(ko)) if ko else "n/d"
        rows.append(
            f"{day} | {int(ki):>6} | {ko_s:>7} | {bal:>8} | "
            f"{int(p):>4}g | {int(c):>4}g | {int(f):>4}g"
        )
        tot_kcal += ki; tot_prot += p; tot_carbs += c; tot_fat += f; n += 1

    if n > 1:
        rows.append(
            f"{'Media':12}| {int(tot_kcal/n):>6} | {'':>7} | {'':>8} | "
            f"{int(tot_prot/n):>4}g | {int(tot_carbs/n):>4}g | {int(tot_fat/n):>4}g"
        )
    return "\n".join(rows)


def _fmt_weight(weight_records: list) -> str:
    records = [(h["health_date"], float(h["weight_kg"])) for h in weight_records if h.get("weight_kg")]
    records.sort()
    if not records:
        return "Nessuna misurazione peso disponibile."
    first_d, first_w = records[0]
    last_d, last_w = records[-1]
    delta = round(last_w - first_w, 1)
    sign = "+" if delta > 0 else ""
    trend_line = " → ".join(f"{w}kg" for _, w in records[-12:])
    return (
        f"Trend: {first_w}kg ({first_d}) → {last_w}kg ({last_d}) = {sign}{delta}kg\n"
        f"Ultime misurazioni: {trend_line}"
    )


def _fmt_health(health_records: list) -> str:
    if not health_records:
        return "Nessun dato disponibile."
    header = "Data        | Sonno  | FC rip  | HRV    | BodyBat | Stress | Passi"
    rows = [header, "-" * len(header)]
    for h in sorted(health_records, key=lambda x: x.get("health_date") or "", reverse=True):
        sleep   = f"{h['sleep_hours']}h"  if h.get("sleep_hours")  else "—"
        fc      = f"{h['resting_hr']}bpm" if h.get("resting_hr")   else "—"
        hrv     = f"{h['hrv_ms']}ms"      if h.get("hrv_ms")       else "—"
        bb      = str(h["body_battery"])  if h.get("body_battery") else "—"
        stress  = str(h["stress_score"])  if h.get("stress_score") else "—"
        steps   = f"{h['steps']:,}"       if h.get("steps")        else "—"
        rows.append(f"{h.get('health_date',''):12}| {sleep:>6} | {fc:>7} | {hrv:>6} | {bb:>7} | {stress:>6} | {steps}")
    return "\n".join(rows)


# ── System prompt ──────────────────────────────────────────────────────────────

_IDENTITY = """\
Sei il coach personale di Marco Ambrosini, con due specializzazioni complementari:
1. Preparatore atletico per ciclismo endurance — lavori con atleti master da oltre 15 anni
2. Nutrizionista sportiva — specializzata in atleti di resistenza over-50

## COME RAGIONI

Per domande di allenamento:
- Esprimi carichi sempre in zone di potenza (Z1–Z5) e nella loro proporzione settimanale
- Valuta il carico ACCUMULATO nelle ultime settimane prima di proporre intensità o volume
- Atleta master 53 anni: recupero più lento, adattamenti più lenti ma duraturi — consistenza > intensità
- Z2 è il fondamento: costruisce base aerobica senza esaurire il SNC
- PRIMA di ogni raccomandazione verifica compatibilità con i vincoli medici; se c'è rischio, proponi alternativa concreta
- Ragiona su trend: se le ultime 2 settimane mostrano affaticamento (HRV bassa, RPE alto, sonno scarso) → proponi recupero, non carico
- Stagionalità: base invernale/primaverile → sviluppo → picco pre-gran fondo

Per domande di nutrizione:
- Obiettivo ricomposizione corporea: deficit ~200-300 kcal nei giorni di recupero; NON nei giorni di allenamento lungo/intenso
- Timing: carboidrati prima + durante sessioni >90 min; proteine subito post (finestra anabolica over-50: entro 30-40 min)
- Fabbisogno proteico: 1.8–2.2g/kg/giorno (critico over-50 per preservare massa muscolare)
- Idratazione + elettroliti nelle sessioni >60 min, specie in salita
- Leggi il bilancio nutrizionale dai dati: commenta se il deficit/surplus è appropriato al giorno di allenamento

Per analisi forma/affaticamento:
- Usa TUTTI i dati: HRV, Body Battery, FC riposo, sonno, RPE, note fisiche, bilancio calorico
- Una singola metrica non basta — cerca convergenza di segnali
- Se Body Battery <50 + HRV bassa + RPE alto negli ultimi 3 giorni → suggerisci recupero attivo (Z1 breve o riposo)
- Se tutto è nella norma e carico è basso → c'è spazio per stimolo

## STILE DI RISPOSTA
- Italiano sempre, tono professionale ma diretto, come un coach di fiducia
- Risposte dense ma non lunghe: max 4 paragrafi (6 per domande complesse)
- Usa numeri concreti: watt, grammi, ore, km — mai solo "aumenta un po'"
- Grassetto per concetti chiave; elenchi solo quando la struttura lo richiede
- No disclaimer medici generici; se c'è controindicazione specifica per Marco, citala
- Se stai continuando una conversazione, non ripetere il contesto già detto\
"""


def _build_system_prompt(
    profile: dict,
    activities: list,
    health_records: list,
    weight_records: list,
    meals_by_day: dict,
    health_by_day: dict,
    today_str: str,
) -> str:
    ftp    = profile.get("ftp_watts") or 202
    z1     = profile.get("power_zone_1_max") or 121
    z2     = profile.get("power_zone_2_max") or 162
    z3     = profile.get("power_zone_3_max") or 182
    z4     = profile.get("power_zone_4_max") or 192
    cmin   = profile.get("target_cadence_min") or 85
    cmax   = profile.get("target_cadence_max") or 95
    medical = profile.get("medical_notes") or (
        "Ernioplastica inguinale bilaterale laparoscopica ottobre 2025, sieroma in riassorbimento. "
        "Evitare sforzi addominali massimali e forte compressione inguinale."
    )
    coaching = profile.get("coaching_notes") or (
        "Ciclista 53 anni, obiettivo gran fondo e riduzione grasso addominale. "
        "2-3 sessioni/settimana, preferibilmente mattina; lungo nel weekend."
    )
    weight_now = profile.get("weight_kg") or \
        next((h.get("weight_kg") for h in health_records if h.get("weight_kg")), "n/d")

    context = f"""
━━━ SNAPSHOT ATLETA — {today_str} ━━━

PROFILO
FTP {ftp}W | Zone: Z1 <{z1}W | Z2 {z1}–{z2}W | Z3 {z2}–{z3}W | Z4 {z3}–{z4}W | Z5 >{z4}W
Cadenza target: {cmin}–{cmax} rpm (difficoltà su pendenze >6-7%)
Peso attuale: {weight_now} kg
Note mediche: {medical}
Obiettivi: {coaching}

━━━ CARICO SETTIMANALE — ULTIME 4 SETTIMANE ━━━
{_weekly_loads(activities)}

━━━ ATTIVITÀ — ULTIMI 30 GIORNI ━━━
{_fmt_activities(activities)}

━━━ CHECK-IN POST-SESSIONE — ULTIMI 10 ━━━
{_fmt_checkins(activities)}

━━━ ANDAMENTO PESO — 30 GIORNI ━━━
{_fmt_weight(weight_records)}

━━━ NUTRIZIONE — ULTIMI 7 GIORNI ━━━
{_fmt_nutrition(meals_by_day, health_by_day)}

━━━ RECUPERO E SALUTE — ULTIMI 14 GIORNI ━━━
{_fmt_health(health_records)}
"""

    return _IDENTITY + "\n\n" + context


# ── Entry point ────────────────────────────────────────────────────────────────

async def get_coach_response(user_id: str, message: str) -> str:
    """Genera risposta di coaching con contesto completo e memoria della sessione."""
    db = get_supabase()
    today_str = date.today().isoformat()
    since_30 = (date.today() - timedelta(days=30)).isoformat()
    since_14 = (date.today() - timedelta(days=14)).isoformat()
    since_7  = (date.today() - timedelta(days=7)).isoformat()

    # ── Fetch dati ──────────────────────────────────────────────────────────────
    profile_res = db.table("user_profiles").select("*").eq("id", user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]

    acts_res = db.table("activities").select("*").eq("user_id", user_id)\
        .gte("activity_date", since_30).order("activity_date", desc=True).execute()
    activities = acts_res.data or []

    meals_res = db.table("meals")\
        .select("meal_date,calories,protein_g,carbs_g,fat_g")\
        .eq("user_id", user_id).gte("meal_date", since_7).execute()
    meals = meals_res.data or []

    health_res = db.table("daily_health").select("*").eq("user_id", user_id)\
        .gte("health_date", since_14).order("health_date", desc=True).execute()
    health_records = health_res.data or []

    weight_res = db.table("daily_health")\
        .select("health_date,weight_kg").eq("user_id", user_id)\
        .gte("health_date", since_30).order("health_date").execute()
    weight_records = [h for h in (weight_res.data or []) if h.get("weight_kg")]

    # ── Aggrega ─────────────────────────────────────────────────────────────────
    meals_by_day: dict = defaultdict(list)
    for m in meals:
        meals_by_day[m.get("meal_date", "")].append(m)

    health_by_day: dict = {h.get("health_date"): h for h in health_records}

    # ── System prompt con snapshot completo ─────────────────────────────────────
    system_prompt = _build_system_prompt(
        profile, activities, health_records, weight_records,
        meals_by_day, health_by_day, today_str,
    )

    # ── Sessione conversazionale ─────────────────────────────────────────────────
    history = _get_active_session(user_id)

    # Costruisci array messaggi: storia precedente + messaggio corrente
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": message})

    # ── Chiamata Claude ─────────────────────────────────────────────────────────
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=system_prompt,
        messages=messages,
    )
    reply = response.content[0].text

    # Salva lo scambio nella sessione
    _save_exchange(user_id, message, reply)

    return reply
