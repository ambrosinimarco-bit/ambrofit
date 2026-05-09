import anthropic
import base64
from pathlib import Path
from backend.config import get_settings

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPT = """Sei un assistente esperto di nutrizione e fitness. Rispondi sempre in italiano e in formato JSON valido (senza markdown). Stima le calorie e i macronutrienti il più precisamente possibile basandoti su banche dati nutrizionali standard. Per porzioni non specificate usa quelle tipiche italiane."""


def _image_to_base64(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("utf-8")


def analyze_food_text(text: str) -> dict:
    """Analizza una descrizione testuale di cibo e restituisce i dati nutrizionali."""
    prompt = f"""Analizza questo pasto e restituisci i dati nutrizionali.
Testo: "{text}"

Rispondi con JSON esatto:
{{
  "meal_name": "nome del pasto",
  "meal_time": "breakfast|lunch|dinner|snack",
  "items": [
    {{"name": "...", "quantity_g": 0, "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}}
  ],
  "total_calories": 0,
  "total_protein_g": 0,
  "total_carbs_g": 0,
  "total_fat_g": 0,
  "total_fiber_g": 0,
  "confidence": "high|medium|low",
  "notes": "eventuali note"
}}"""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    return json.loads(response.content[0].text)


def analyze_food_photo(image_bytes: bytes, extra_context: str = "") -> dict:
    """Analizza una foto di cibo e stima i valori nutrizionali."""
    b64 = _image_to_base64(image_bytes)
    context_line = f"\nContexto aggiuntivo: {extra_context}" if extra_context else ""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                },
                {
                    "type": "text",
                    "text": f"""Identifica i piatti/alimenti nella foto e stima i valori nutrizionali.{context_line}

Rispondi con JSON esatto:
{{
  "meal_name": "nome del pasto identificato",
  "meal_time": "breakfast|lunch|dinner|snack",
  "items": [
    {{"name": "...", "quantity_g": 0, "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}}
  ],
  "total_calories": 0,
  "total_protein_g": 0,
  "total_carbs_g": 0,
  "total_fat_g": 0,
  "total_fiber_g": 0,
  "confidence": "high|medium|low",
  "notes": "cosa hai identificato e come hai stimato"
}}""",
                },
            ],
        }],
    )
    import json
    return json.loads(response.content[0].text)


def analyze_nutrition_label(image_bytes: bytes, quantity_g: float = 100) -> dict:
    """Legge un'etichetta alimentare e calcola i valori per la quantità indicata."""
    b64 = _image_to_base64(image_bytes)

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                },
                {
                    "type": "text",
                    "text": f"""Leggi questa etichetta alimentare. L'utente ha consumato {quantity_g}g del prodotto.

Rispondi con JSON esatto:
{{
  "product_name": "nome prodotto",
  "per_100g": {{"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0, "sugar_g": 0, "salt_g": 0}},
  "per_quantity": {{"quantity_g": {quantity_g}, "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}},
  "ingredients_summary": "breve riassunto ingredienti principali",
  "allergens": [],
  "confidence": "high|medium|low"
}}""",
                },
            ],
        }],
    )
    import json
    return json.loads(response.content[0].text)


def analyze_garmin_screenshot(image_bytes: bytes) -> dict:
    """Estrae dati fitness da uno screenshot di Garmin Connect (salute o attività ciclistica)."""
    b64 = _image_to_base64(image_bytes)

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                },
                {
                    "type": "text",
                    "text": """Questo è uno screenshot di Garmin Connect. Determina se mostra dati di salute giornaliera o un'attività ciclistica, poi estrai tutti i dati visibili.

Rispondi con JSON esatto (usa null per i valori non visibili):
{
  "screen_type": "health|activity|mixed",
  "date": "YYYY-MM-DD o null",
  "body_battery_start": null,
  "body_battery_end": null,
  "stress_score": null,
  "hrv_ms": null,
  "resting_hr": null,
  "sleep_hours": null,
  "sleep_score": null,
  "sleep_deep_h": null,
  "sleep_light_h": null,
  "sleep_rem_h": null,
  "steps": null,
  "calories_active": null,
  "calories_total": null,
  "intensity_minutes": null,
  "activity_name": null,
  "avg_power_w": null,
  "normalized_power_w": null,
  "avg_cadence_rpm": null,
  "avg_hr_bpm": null,
  "max_hr_bpm": null,
  "duration_min": null,
  "distance_km": null,
  "elevation_m": null,
  "tss": null,
  "raw_text": "testo grezzo rilevante dallo screenshot"
}""",
                },
            ],
        }],
    )
    import json
    return json.loads(response.content[0].text)


def analyze_voice_transcript(transcript: str) -> dict:
    """Interpreta un messaggio (testo o voce) e determina il tipo di dato o correzione."""
    prompt = f"""Analizza questo messaggio e determina cosa vuole registrare o correggere l'utente.
Messaggio: "{transcript}"

Rispondi con JSON esatto:
{{
  "type": "meal|activity|total_calories_iphone|weight|sleep|steps|correction|status|check_in|pre_condition|coach|zwo_request|general",
  "data": {{
    "meal_name": "...", "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "meal_time": "snack",
    "activity_type": "run|ride|swim|walk|strength|other", "duration_min": 0, "distance_km": null, "name": "...",
    "weight_kg": null, "sleep_hours": null, "steps": null,
    "total_calories_iphone": null,
    "entity_type": "meal|activity|weight|sleep|steps",
    "description": "cosa correggere in italiano",
    "corrections": {{}},
    "rpe": null,
    "physical_notes": null,
    "condition_pre": null,
    "condition_during": null,
    "condition_post": null,
    "stress_level": null
  }},
  "confidence": "high|medium|low"
}}

Regole per il tipo:
- total_calories_iphone: usa quando l'utente registra il TOTALE calorie della giornata da iPhone/Apple Fitness (include già BMR+movimento+sport). Es: "le mie calorie totali sono 2400", "iPhone fitness: 2800 kcal", "calorie totali giornata 2350"
- correction: usa quando corregge dati precedenti. Es: "correggimi l'ultimo pasto", "la mela pesava 150g non 200g", "ho sbagliato il peso di prima"
- activity: attività sportiva specifica con durata. Es: "ho fatto 1 ora di bici"
- meal: cibo mangiato. Es: "ho mangiato una mela"
- status: vuole sapere come sta oggi / quanto può mangiare. Es: "come sto oggi", "dimmi la situazione", "quanto posso ancora mangiare", "status", "riepilogo"
- check_in: l'utente risponde al check-in post-sessione con qualsiasi combinazione di: voto RPE, condizione pre/durante/post, ore sonno, stress. Es: "8, ero stanco prima ma è andata bene", "RPE 7, dormito 6h, stress 4". Estrai tutti i campi disponibili: rpe (int 1-10), physical_notes, condition_pre, condition_during, condition_post, sleep_hours, stress_level.
- pre_condition: l'utente descrive come si sente PRIMA di allenarsi o come ha dormito, SENZA registrare un'attività specifica con durata. Es: "stamattina mi sento stanco", "ho dormito 5 ore, gambe pesanti", "oggi sono molto stressato". Estrai: condition_pre, sleep_hours (se menzionate), stress_level (se menzionato).
- coach: domanda/frase di coaching (es. "come sto andando", "ho saltato la sessione di mercoledì", "crea un piano per questa settimana"). NON usare per registrare dati specifici.
- zwo_request: richiesta esplicita di generare file .zwo per allenamento indoor (es. "crea una sessione z2 45 minuti", "generami un workout sweetspot di 1 ora").
"""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    return json.loads(response.content[0].text)


def generate_training_plan(user_profile: dict, request: str) -> dict:
    """Genera un piano di allenamento personalizzato."""
    prompt = f"""Crea un piano di allenamento personalizzato.

Profilo utente:
{user_profile}

Richiesta: "{request}"

Rispondi con JSON esatto:
{{
  "plan_name": "nome piano",
  "goal": "obiettivo principale",
  "description": "descrizione breve",
  "duration_weeks": 0,
  "weekly_sessions": 0,
  "sessions": [
    {{
      "week": 1,
      "day_of_week": "monday|tuesday|wednesday|thursday|friday|saturday|sunday",
      "activity_type": "run|ride|swim|walk|strength|yoga|other",
      "title": "titolo sessione",
      "description": "descrizione dettagliata con esercizi",
      "duration_target_min": 0,
      "distance_target_km": null,
      "intensity": "easy|moderate|hard"
    }}
  ],
  "notes": "consigli generali"
}}"""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    return json.loads(response.content[0].text)


def adjust_training_plan(plan_context: dict, adjustment_reason: str) -> dict:
    """Ricalibra un piano di allenamento esistente."""
    prompt = f"""L'utente deve modificare il suo piano di allenamento.

Piano attuale:
{plan_context}

Motivo della modifica: "{adjustment_reason}"

Analizza la situazione e rispondi con JSON:
{{
  "assessment": "breve valutazione della situazione",
  "recommended_changes": [
    {{"session_id": "id", "action": "skip|reduce_intensity|postpone|replace", "new_description": "...", "reason": "..."}}
  ],
  "motivational_message": "messaggio di supporto all'utente",
  "overall_impact": "minimal|moderate|significant"
}}"""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    return json.loads(response.content[0].text)


def suggest_exercises(user_profile: dict, available_time_min: int = 45) -> dict:
    """Suggerisce esercizi specifici in base all'obiettivo dell'utente."""
    prompt = f"""Suggerisci una sessione di allenamento per oggi.

Profilo: {user_profile}
Tempo disponibile: {available_time_min} minuti

Rispondi con JSON:
{{
  "session_title": "titolo sessione",
  "warm_up": [{{"exercise": "...", "duration_min": 0, "sets": null, "reps": null, "notes": "..."}}],
  "main_workout": [{{"exercise": "...", "duration_min": null, "sets": 0, "reps": 0, "rest_sec": 60, "notes": "..."}}],
  "cool_down": [{{"exercise": "...", "duration_min": 0, "notes": "..."}}],
  "total_duration_min": 0,
  "estimated_calories": 0,
  "focus": "cardio|strength|mobility|hiit|mixed",
  "why": "perché questa sessione è utile per il tuo obiettivo"
}}"""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    return json.loads(response.content[0].text)


def plan_zwo_workout(request: str, ftp: int) -> dict:
    """Genera struttura JSON di un workout indoor .zwo a partire da una richiesta in linguaggio naturale."""
    prompt = f"""Crea un workout indoor per ciclismo basato su questa richiesta: "{request}"
L'utente ha FTP di {ftp}W.

Rispondi con JSON esatto:
{{
  "name": "Nome workout (es. Z2 Endurance 60min)",
  "description": "Descrizione breve del workout e obiettivo",
  "segments": [
    {{"type": "Warmup", "duration_min": 10, "power_low": 0.50, "power_high": 0.75}},
    {{"type": "SteadyState", "duration_min": 45, "power": 0.70}},
    {{"type": "Cooldown", "duration_min": 5, "power_low": 0.55, "power_high": 0.35}}
  ]
}}

Tipi segmento validi:
- Warmup: richiede duration_min, power_low, power_high
- SteadyState: richiede duration_min, power (frazione FTP, es. 0.70 per Z2, 0.88 per SS, 1.05 per VO2max)
- Cooldown: richiede duration_min, power_high (iniziale), power_low (finale)
- IntervalsT: richiede repeat (numero ripetizioni), on_duration_min, off_duration_min, on_power, off_power

Usa sempre riscaldamento (almeno 8-10min) e defaticamento (almeno 5min).
Power come frazione FTP: Z2=0.60-0.75, SweetSpot=0.85-0.95, Threshold=0.95-1.05, VO2max=1.05-1.20."""

    import json
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(response.content[0].text)


def generate_daily_status(summary: dict, user_profile: dict) -> dict:
    """Genera suggerimenti alimentari e messaggio motivazionale basati sulla situazione di oggi."""
    remaining_kcal = round(summary["calorie_goal"] - summary["calories_in"])
    remaining_protein = round(user_profile.get("protein_goal_g", 150) - summary["protein_g"])
    remaining_carbs = round(user_profile.get("carbs_goal_g", 280) - summary["carbs_g"])
    remaining_fat = round(user_profile.get("fat_goal_g", 75) - summary["fat_g"])

    calories_out_source = "iPhone Fitness" if summary.get("total_calories_iphone") else "stima BMR"

    prompt = f"""Sei un coach nutrizionale e di ciclismo per Marco, atleta endurance che vuole migliorare la performance ciclistica e ridurre il grasso addominale.

Situazione di oggi:
- Calorie assunte: {summary['calories_in']} / {summary['calorie_goal']} kcal (rimangono {remaining_kcal} kcal)
- Calorie bruciate: {summary['calories_out']} kcal ({calories_out_source})
- Bilancio netto: {summary['net_calories']:+.0f} kcal
- Proteine: {summary['protein_g']}g / {user_profile.get('protein_goal_g', 150)}g (rimangono {remaining_protein}g)
- Carboidrati: {summary['carbs_g']}g / {user_profile.get('carbs_goal_g', 280)}g (rimangono {remaining_carbs}g)
- Grassi: {summary['fat_g']}g / {user_profile.get('fat_goal_g', 75)}g (rimangono {remaining_fat}g)
- Attività oggi: {len(summary.get('activities', []))} allenamenti registrati
- Peso attuale: {summary.get('weight_kg') or user_profile.get('weight_kg', '?')} kg

Obiettivi: endurance ciclistica, ricomposizione corporea, riduzione grasso addominale.

Rispondi in JSON esatto:
{{
  "suggestion": "suggerimento pratico (2-3 frasi max) su cosa mangiare nel resto della giornata per centrare gli obiettivi senza sforare — nomina cibi specifici adatti a un ciclista",
  "motivation": "messaggio motivazionale breve (1-2 frasi) legato al ciclismo e all'obiettivo di Marco — varia il tono tra incoraggiante, sfidante e concreto"
}}"""

    import json
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(response.content[0].text)
