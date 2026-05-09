"""Coach service: risponde a domande di coaching con contesto completo dell'utente."""
import anthropic
from datetime import date, timedelta
from backend.config import get_settings
from backend.database.client import get_supabase

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPT_TEMPLATE = """\
Sei il coach personale di Marco Ambrosini. Hai due specializzazioni complementari:
1. **Preparatore atletico per ciclismo endurance** — lavori con atleti master da oltre 15 anni
2. **Nutrizionista sportiva** — specializzata in atleti di resistenza over-50

---

## PROFILO ATLETA

**Marco Ambrosini**, 53 anni, ciclista amatoriale avanzato.

**Parametri fisiologici:**
- FTP: {ftp_watts}W
- Zone di potenza:
  - Z1 Recupero attivo: <{z1}W
  - Z2 Base aerobica: {z1}–{z2}W
  - Z3 Tempo: {z2}–{z3}W
  - Z4 Soglia / Sweet Spot: {z3}–{z4}W
  - Z5 VO2max e oltre: >{z4}W
- Cadenza target: {cad_min}–{cad_max} rpm
  (nota: difficoltà a mantenere la cadenza su pendenze >6-7%)

**Storia medica — PRIORITÀ ASSOLUTA:**
{medical_notes}

**Regola inderogabile:** prima di ogni raccomandazione di allenamento,
verifica che non coinvolga sforzi addominali massimali o compressione
inguinale. In caso di dubbio, proponi alternative sicure.

**Obiettivi e stile:**
{coaching_notes}

---

## CONTESTO CORRENTE

Data di oggi: {today}
Peso attuale: {weight_kg} kg

**Ultimi 7 giorni — Attività:**
{activities_summary}

**Ultimi 7 giorni — Nutrizione:**
{nutrition_summary}

**Ultimi 7 giorni — Salute e recupero:**
{health_summary}

---

## COME RAGIONI

### Per domande di allenamento:
- Esprimi carichi sempre in zone di potenza (Z1/Z2/Z3/Z4/Z5)
- Valuta il carico accumulato negli ultimi 7 giorni prima di proporre
  intensità o volume
- Per un atleta master di 53 anni: recupero più lento, adattamenti
  più lenti ma più duraturi — privilegia consistenza su intensità
- Tieni il volume Z2 come fondamento (costruisce la base aerobica
  senza esaurire il sistema nervoso)
- Segnala sempre se la proposta è compatibile con i vincoli medici
- Considera stagionalità: obiettivo gran fondo → costruzione base
  in inverno/primavera, picco in estate/autunno

### Per domande di nutrizione:
- Marco è ciclista che vuole ridurre grasso addominale mantenendo
  performance → deficit calorico moderato (~200-300 kcal), MAI nelle
  giornate di allenamento intenso o lungo
- Timing: carboidrati prima e durante le sessioni >90 min, proteine
  subito dopo (finestra anabolica critica over-50: entro 30-40 min)
- Fabbisogno proteico elevato per atleta master: 1.8–2.2g/kg/giorno
  per mantenere massa muscolare
- Idratazione: critica, specie in salita; elettroliti nelle sessioni >60 min
- Nei giorni di recupero: riduzione carboidrati, mantenimento proteine

### Per domande generali o check-in:
- Commenta i dati recenti in modo costruttivo
- Identifica pattern positivi e aree di miglioramento
- Non fare domande retoriche — dai indicazioni concrete

---

## STILE DI RISPOSTA

- **Lingua:** italiano sempre
- **Tono:** professionale ma conversazionale, come un coach di fiducia
- **Lunghezza:** conciso e denso. Max 4 paragrafi per risposta standard;
  max 6 per domande complesse (es. piano settimanale, analisi stagione)
- **Formato:** usa grassetto per concetti chiave, elenchi puntati solo
  se la risposta lo richiede strutturalmente
- **Numeri:** cita sempre watt, grammi, ore — non restare sul vago
- **No disclaimer medici generici:** se c'è una controindicazione
  specifica per Marco, citala; altrimenti non aggiungere "consulta
  il medico" per ogni risposta
"""


def _build_activities_summary(activities: list) -> str:
    if not activities:
        return "Nessuna attività registrata negli ultimi 7 giorni."
    lines = []
    for a in activities:
        parts = [f"• {a.get('activity_date', '')} — {a.get('name', 'Attività')} ({a.get('activity_type', 'altro')})"]
        details = []
        if a.get("duration_min"):
            details.append(f"{a['duration_min']}min")
        if a.get("distance_km"):
            details.append(f"{a['distance_km']}km")
        if a.get("avg_heart_rate"):
            details.append(f"FC avg {a['avg_heart_rate']} bpm")
        if a.get("elevation_m"):
            details.append(f"+{a['elevation_m']}m D+")
        if a.get("rpe"):
            details.append(f"RPE {a['rpe']}/10")
        if details:
            parts.append(f"[{' | '.join(details)}]")
        if a.get("physical_notes"):
            parts.append(f"⚠ {a['physical_notes']}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _build_nutrition_summary(meals_by_day: dict) -> str:
    if not meals_by_day:
        return "Nessun dato nutrizionale disponibile."
    lines = []
    for day in sorted(meals_by_day.keys(), reverse=True):
        meals = meals_by_day[day]
        kcal = sum(m.get("calories", 0) or 0 for m in meals)
        prot = sum(m.get("protein_g", 0) or 0 for m in meals)
        carbs = sum(m.get("carbs_g", 0) or 0 for m in meals)
        fat = sum(m.get("fat_g", 0) or 0 for m in meals)
        lines.append(f"• {day}: {round(kcal)} kcal | P {round(prot)}g | C {round(carbs)}g | G {round(fat)}g")
    return "\n".join(lines)


def _build_health_summary(health_records: list) -> str:
    if not health_records:
        return "Nessun dato di salute disponibile."
    lines = []
    for h in health_records:
        parts = [f"• {h.get('health_date', '')}"]
        details = []
        if h.get("weight_kg"):
            details.append(f"peso {h['weight_kg']}kg")
        if h.get("sleep_hours"):
            details.append(f"sonno {h['sleep_hours']}h")
        if h.get("resting_hr"):
            details.append(f"FC riposo {h['resting_hr']} bpm")
        if h.get("hrv_ms"):
            details.append(f"HRV {h['hrv_ms']}ms")
        if h.get("body_battery"):
            details.append(f"Body Battery {h['body_battery']}")
        if h.get("stress_score"):
            details.append(f"stress {h['stress_score']}")
        if h.get("steps"):
            details.append(f"passi {h['steps']:,}")
        if details:
            parts.append(": " + " | ".join(details))
        lines.append("".join(parts))
    return "\n".join(lines) if lines else "Nessun dato di salute disponibile."


async def get_coach_response(user_id: str, message: str) -> str:
    """Genera una risposta di coaching con contesto completo degli ultimi 7 giorni."""
    db = get_supabase()
    today_str = date.today().isoformat()
    since = (date.today() - timedelta(days=7)).isoformat()

    # Fetch parallelo dei dati
    profile_res = db.table("user_profiles").select("*").eq("id", user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]

    acts_res = db.table("activities").select("*").eq("user_id", user_id)\
        .gte("activity_date", since).order("activity_date", desc=True).limit(15).execute()
    activities = acts_res.data or []

    meals_res = db.table("meals").select("meal_date,calories,protein_g,carbs_g,fat_g")\
        .eq("user_id", user_id).gte("meal_date", since).order("meal_date", desc=True).execute()
    meals = meals_res.data or []

    health_res = db.table("daily_health").select("*").eq("user_id", user_id)\
        .gte("health_date", since).order("health_date", desc=True).execute()
    health_records = health_res.data or []

    # Raggruppa pasti per giorno
    meals_by_day: dict = {}
    for m in meals:
        d = m.get("meal_date", "")
        meals_by_day.setdefault(d, []).append(m)

    # Estrai dati profilo con fallback
    ftp = profile.get("ftp_watts") or 202
    z1 = profile.get("power_zone_1_max") or 121
    z2 = profile.get("power_zone_2_max") or 162
    z3 = profile.get("power_zone_3_max") or 182
    z4 = profile.get("power_zone_4_max") or 192
    cad_min = profile.get("target_cadence_min") or 85
    cad_max = profile.get("target_cadence_max") or 95
    medical_notes = profile.get("medical_notes") or \
        "Ernioplastica inguinale bilaterale laparoscopica ottobre 2025, sieroma in riassorbimento. " \
        "Evitare sforzi addominali massimali e forte compressione inguinale."
    coaching_notes = profile.get("coaching_notes") or \
        "Ciclista 53 anni, obiettivo migliorare performance gran fondo, ridurre grasso addominale. " \
        "2-3 sessioni settimanali preferibilmente mattina, lungo nel weekend."
    weight_kg = profile.get("weight_kg") or \
        next((h.get("weight_kg") for h in health_records if h.get("weight_kg")), "n/d")

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        ftp_watts=ftp,
        z1=z1, z2=z2, z3=z3, z4=z4,
        cad_min=cad_min, cad_max=cad_max,
        medical_notes=medical_notes,
        coaching_notes=coaching_notes,
        today=today_str,
        weight_kg=weight_kg,
        activities_summary=_build_activities_summary(activities),
        nutrition_summary=_build_nutrition_summary(meals_by_day),
        health_summary=_build_health_summary(health_records),
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text
