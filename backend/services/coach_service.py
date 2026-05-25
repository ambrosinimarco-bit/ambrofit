"""Coach service con memoria contestuale completa (30gg) e sessioni conversazionali."""
import asyncio
import uuid
import anthropic
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from backend.config import get_settings
from backend.database.client import get_supabase
from backend.services.nutrition_service import get_daily_summary

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# ── Sessioni in memoria (max 2 ore di continuità) ──────────────────────────────

SESSION_TIMEOUT = timedelta(hours=2)
# user_id -> {"session_id": str, "messages": [{"role", "content", "ts"}]}
_sessions: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_session_id() -> str:
    return str(uuid.uuid4())


def _get_active_session(user_id: str) -> tuple[list[dict], str]:
    """Ritorna (history, session_id). Crea nuova sessione se scaduta o assente."""
    session = _sessions.get(user_id)
    if session:
        msgs = session["messages"]
        if not msgs or (_now() - msgs[-1]["ts"]) <= SESSION_TIMEOUT:
            return msgs, session["session_id"]
    # Nuova sessione
    sid = _generate_session_id()
    _sessions[user_id] = {"session_id": sid, "messages": []}
    return [], sid


def _save_exchange_memory(user_id: str, user_msg: str, assistant_msg: str, session_id: str) -> None:
    if user_id not in _sessions:
        _sessions[user_id] = {"session_id": session_id, "messages": []}
    msgs = _sessions[user_id]["messages"]
    now = _now()
    msgs.append({"role": "user",      "content": user_msg,      "ts": now})
    msgs.append({"role": "assistant", "content": assistant_msg, "ts": now})
    if len(msgs) > 40:
        _sessions[user_id]["messages"] = msgs[-40:]


# ── Persistenza DB ─────────────────────────────────────────────────────────────

def _save_exchange_db(user_id: str, session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Salva lo scambio nel database (fire-and-forget, non bloccante sul caller)."""
    try:
        db = get_supabase()
        db.table("coach_conversations").insert([
            {"user_id": user_id, "session_id": session_id, "role": "user",      "message": user_msg},
            {"user_id": user_id, "session_id": session_id, "role": "assistant", "message": assistant_msg},
        ]).execute()
    except Exception:
        pass  # non interrompere il flusso se il salvataggio fallisce


def _load_history_db(
    user_id: str,
    exclude_session_id: str | None = None,
    days: int = 7,
    limit: int = 20,
) -> list[dict]:
    """Carica messaggi recenti dal DB, esclusa la sessione corrente."""
    try:
        db = get_supabase()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        q = (
            db.table("coach_conversations")
            .select("role,message,session_id,created_at")
            .eq("user_id", user_id)
            .gte("created_at", since)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if exclude_session_id:
            q = q.neq("session_id", exclude_session_id)
        rows = q.execute().data or []
        rows.sort(key=lambda r: r.get("created_at") or "")
        return [{"role": r["role"], "content": r["message"]} for r in rows]
    except Exception:
        return []


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


def _fmt_objectives(objectives: list) -> str:
    if not objectives:
        return "Nessun obiettivo attivo."
    lines = []
    today = date.today()
    for o in objectives:
        title   = o.get("title") or "Obiettivo"
        otype   = o.get("type") or "open"
        tdate   = o.get("target_date")
        desc    = o.get("description") or ""
        plan    = o.get("plan_name") or ""
        done    = o.get("completed_sessions") or 0
        total   = o.get("total_sessions") or 0
        pct     = o.get("completion_pct") or 0

        line = f"• {tdate or '—'} — {title} ({otype})"

        if tdate:
            try:
                days_left = (date.fromisoformat(tdate) - today).days
                if days_left > 0:
                    line += f" — tra {days_left} giorni"
                elif days_left == 0:
                    line += " — OGGI"
                else:
                    line += f" — scaduto {abs(days_left)}gg fa"
            except ValueError:
                pass

        if desc:
            line += f"\n  {desc}"
        if plan:
            line += f"\n  Piano: {plan}"
            if total > 0:
                line += f" ({done}/{total} sessioni, {round(pct)}%)"
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
- Se stai continuando una conversazione, non ripetere il contesto già detto
- Non fare mai riferimento al numero di volte che l'utente ha fatto una domanda. Non dire frasi come "è la terza volta che chiedi" o simili. Ogni domanda va trattata con rispetto e senza commenti sul comportamento dell'utente.\
"""


def _fmt_db_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for m in history:
        label = "Marco" if m["role"] == "user" else "Coach"
        content = m["content"].replace("\n", " ")[:400]
        lines.append(f"[{label}]: {content}")
    return "\n".join(lines)


def _build_system_prompt(
    profile: dict,
    activities: list,
    health_records: list,
    weight_records: list,
    meals_by_day: dict,
    health_by_day: dict,
    today_str: str,
    db_history: list[dict] | None = None,
    today_summary: dict | None = None,
    objectives: list | None = None,
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
    weight_now = (
        next((h.get("weight_kg") for h in health_records if h.get("weight_kg")), None)
        or profile.get("weight_kg")
        or "n/d"
    )

    macro_line = ""
    if today_summary:
        cal_t  = today_summary.get("calories_for_macros") or today_summary.get("calorie_goal")
        prot_t = today_summary.get("protein_goal_g")
        carb_t = today_summary.get("carbs_goal_g")
        fat_t  = today_summary.get("fat_goal_g")
        dyn    = today_summary.get("macro_targets_dynamic", False)
        print(f"[coach] today_summary targets: cal={cal_t} prot={prot_t} carb={carb_t} fat={fat_t} dyn={dyn}", flush=True)
        if cal_t:
            macro_line = (
                f"\nTARGET NUTRIZIONALI PRECISI DI OGGI (calcolati dal sistema, usa SOLO questi valori, non stimare autonomamente):\n"
                f"- Calorie target: {round(cal_t)} kcal\n"
                f"- Proteine target: {round(prot_t or 0)}g\n"
                f"- Carboidrati target: {round(carb_t or 0)}g\n"
                f"- Grassi target: {round(fat_t or 0)}g\n"
                f"IMPORTANTE: non usare valori diversi da questi per valutare la nutrizione dell'utente."
            )
    else:
        print("[coach] today_summary non disponibile — target macro assenti dal contesto", flush=True)

    context = f"""
━━━ SNAPSHOT ATLETA — {today_str} ━━━

PROFILO
FTP {ftp}W | Zone: Z1 <{z1}W | Z2 {z1}–{z2}W | Z3 {z2}–{z3}W | Z4 {z3}–{z4}W | Z5 >{z4}W
Cadenza target: {cmin}–{cmax} rpm (difficoltà su pendenze >6-7%)
Peso attuale: {weight_now} kg{macro_line}
Note mediche: {medical}
Note coaching: {coaching}

━━━ OBIETTIVI ATTIVI ━━━
{_fmt_objectives(objectives or [])}

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

    if db_history:
        context += f"\n\n━━━ CONVERSAZIONI RECENTI (ultimi 7 giorni) ━━━\n{_fmt_db_history(db_history)}"

    return _IDENTITY + "\n\n" + context


# ── Shared data fetching ───────────────────────────────────────────────────────

def _build_coach_prompt(user_id: str, exclude_session_id: str | None = None) -> str:
    """Recupera tutti i dati dal DB e costruisce il system prompt completo."""
    db = get_supabase()
    today_str = date.today().isoformat()
    since_30 = (date.today() - timedelta(days=30)).isoformat()
    since_14 = (date.today() - timedelta(days=14)).isoformat()
    since_7  = (date.today() - timedelta(days=7)).isoformat()

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

    meals_by_day: dict = defaultdict(list)
    for m in meals:
        meals_by_day[m.get("meal_date", "")].append(m)
    health_by_day: dict = {h.get("health_date"): h for h in health_records}

    db_history = _load_history_db(user_id, exclude_session_id=exclude_session_id)

    try:
        today_summary = get_daily_summary(user_id, date.today())
    except Exception as e:
        print(f"[coach] get_daily_summary failed: {e}", flush=True)
        today_summary = None

    try:
        obj_res = db.table("v_objective_progress").select(
            "objective_id,title,description,type,status,target_date,plan_name,"
            "completion_pct,total_sessions,completed_sessions"
        ).eq("user_id", user_id).eq("status", "active").order("target_date", nullsfirst=False).execute()
        objectives = obj_res.data or []
    except Exception as e:
        print(f"[coach] objectives fetch failed: {e}", flush=True)
        objectives = []

    return _build_system_prompt(
        profile, activities, health_records, weight_records,
        meals_by_day, health_by_day, today_str,
        db_history=db_history,
        today_summary=today_summary,
        objectives=objectives,
    )


def _call_claude(system_prompt: str, messages: list[dict]) -> str:
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8192,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


# ── Entry points ───────────────────────────────────────────────────────────────

async def get_coach_response(user_id: str, message: str) -> str:
    """Telegram: usa le sessioni in memoria (2 ore di continuità) + storico DB.
    Le chiamate bloccanti (DB + Anthropic) girano in thread separati per non
    congelare l'event loop asyncio del bot."""
    history, session_id = _get_active_session(user_id)

    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": message})

    system_prompt = await asyncio.to_thread(_build_coach_prompt, user_id, session_id)
    reply = await asyncio.to_thread(_call_claude, system_prompt, messages)

    _save_exchange_memory(user_id, message, reply, session_id)
    await asyncio.to_thread(_save_exchange_db, user_id, session_id, message, reply)
    return reply


async def get_coach_response_web(
    user_id: str,
    message: str,
    history: list[dict],
    session_id: str | None = None,
) -> tuple[str, str]:
    """Web dashboard: sessione gestita dal frontend. Ritorna (reply, session_id)."""
    if not session_id:
        session_id = _generate_session_id()

    messages = list(history)
    messages.append({"role": "user", "content": message})

    system_prompt = await asyncio.to_thread(_build_coach_prompt, user_id, session_id)
    reply = await asyncio.to_thread(_call_claude, system_prompt, messages)

    await asyncio.to_thread(_save_exchange_db, user_id, session_id, message, reply)
    return reply, session_id
