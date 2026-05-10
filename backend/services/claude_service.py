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
  "meal_name": "solo nome alimento + marca se presente (es. 'Piada Riminese La Spessa', 'Stracchino Conad', 'Banana'). NON includere orario, quantità, verbi o contesto.",
  "meal_time": "breakfast|lunch|dinner|snack",
  "items": [
    {{
      "name": "nome alimento SENZA brand (es. 'Stracchino', 'Gnocchi', 'Banana')",
      "brand": "brand/marca se presente, null altrimenti (es. 'Conad', 'Coop', null)",
      "quantity_g": 0, "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0
    }}
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


_GARMIN_JSON_SCHEMA = """{
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
  "raw_text": "testo grezzo rilevante dagli screenshot"
}"""


def analyze_garmin_screenshots_batch(images: list[bytes]) -> dict:
    """Analyze one or more Garmin screenshots in a single API call, merging all data."""
    import json

    content: list[dict] = []
    for img_bytes in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": _image_to_base64(img_bytes)},
        })

    n = len(images)
    if n == 1:
        intro = "Questo è uno screenshot di Garmin Connect. Estrai tutti i dati visibili."
    else:
        intro = (
            f"Questi sono {n} screenshot di Garmin Connect dello stesso utente/sessione. "
            "Ogni immagine può mostrare una schermata diversa (velocità, potenza, cadenza, "
            "salute, ecc.). Analizzali tutti e unisci i dati in un unico JSON consolidato: "
            "se un valore appare in più screenshot usa quello più preciso/dettagliato. "
            "Determina il screen_type complessivo ('mixed' se ci sono sia salute che attività)."
        )

    content.append({
        "type": "text",
        "text": (
            f"{intro}\n\n"
            f"Rispondi con JSON esatto (null per valori non visibili in nessuno screenshot):\n"
            f"{_GARMIN_JSON_SCHEMA}"
        ),
    })

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return json.loads(response.content[0].text)


def classify_photo_type(image_bytes: bytes) -> str:
    """Fast visual classification: 'garmin' | 'food' | 'label'.
    Uses Haiku for low latency — only called when caption gives no signal.
    """
    b64 = _image_to_base64(image_bytes)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=15,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": (
                    "Look at this image. Reply with exactly one word:\n"
                    "- 'garmin' if it shows fitness/sports data (heart rate, power, Body Battery, "
                    "HRV, km, steps, sleep, activity summary from Garmin or similar app)\n"
                    "- 'label' if it shows a nutrition facts/ingredients label\n"
                    "- 'food' for anything else (meal, food photo)\n"
                    "One word only."
                )},
            ],
        }],
    )
    word = resp.content[0].text.strip().lower().split()[0]
    if word == "garmin":
        return "garmin"
    if word == "label":
        return "label"
    return "food"


def generate_activity_report(
    garmin_data: dict,
    recent_acts: list[dict],
    profile: dict,
    ftp: int = 202,
) -> str:
    """Generates a concise post-activity coaching report in Italian Markdown."""
    # Build recent activity summary (last 7, most relevant fields)
    recent_lines = []
    for a in recent_acts[:7]:
        parts = [a.get("activity_date", ""), a.get("name", "")]
        if a.get("duration_min"):
            parts.append(f"{int(a['duration_min'])}min")
        if a.get("avg_power_w"):
            parts.append(f"{a['avg_power_w']}W")
        if a.get("tss"):
            parts.append(f"TSS {a['tss']}")
        recent_lines.append(" · ".join(str(p) for p in parts if p))
    recent_block = "\n".join(f"  - {l}" for l in recent_lines) or "  Nessuna attività recente"

    # Garmin fields
    g = garmin_data
    data_block = "\n".join(filter(None, [
        f"- Nome: {g.get('activity_name') or 'Attività'}" ,
        f"- Durata: {g.get('duration_min')} min" if g.get("duration_min") else None,
        f"- Distanza: {g.get('distance_km')} km" if g.get("distance_km") else None,
        f"- Dislivello: {g.get('elevation_m')} m" if g.get("elevation_m") else None,
        f"- Potenza media: {g.get('avg_power_w')}W" if g.get("avg_power_w") else None,
        f"- NP: {g.get('normalized_power_w')}W" if g.get("normalized_power_w") else None,
        f"- FC media: {g.get('avg_hr_bpm')} bpm" if g.get("avg_hr_bpm") else None,
        f"- Cadenza: {g.get('avg_cadence_rpm')} rpm" if g.get("avg_cadence_rpm") else None,
        f"- TSS: {g.get('tss')}" if g.get("tss") else None,
        f"- Body Battery inizio: {g.get('body_battery_start')}" if g.get("body_battery_start") else None,
        f"- Body Battery fine: {g.get('body_battery_end')}" if g.get("body_battery_end") else None,
        f"- HRV: {g.get('hrv_ms')} ms" if g.get("hrv_ms") else None,
        f"- Stress: {g.get('stress_score')}" if g.get("stress_score") else None,
        f"- Sonno: {g.get('sleep_hours')}h (score {g.get('sleep_score')})" if g.get("sleep_hours") else None,
    ]))

    prompt = f"""Sei il coach di Marco, ciclista 53 anni.

DATI ATTIVITÀ:
{data_block}

PROFILO:
- FTP: {ftp}W
- Zone potenza: Z1<{int(ftp*0.56)}W | Z2 {int(ftp*0.56)}-{int(ftp*0.75)}W | Z3 {int(ftp*0.75)}-{int(ftp*0.87)}W | Z4 {int(ftp*0.87)}-{int(ftp*1.05)}W | Z5>{int(ftp*1.05)}W
- Obiettivo: Granfondo Novecolli 24 maggio 2026

ATTIVITÀ RECENTI (14 giorni):
{recent_block}

Genera un report post-attività in Markdown, max 20 righe, con queste sezioni:
1. **Riepilogo** — dati chiave in 2 righe
2. **Performance** — analisi rispetto alle zone FTP, confronto con uscite simili
3. **Recupero** — valutazione BB e HRV, stima ore necessarie
4. **Prossima sessione** — tipo, intensità, durata consigliati
5. **Nutrizione** — cosa mangiare nelle prossime 2-3 ore

Sii diretto, usa i numeri reali, niente frasi generiche."""

    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def analyze_voice_transcript(transcript: str) -> dict:
    """Interpreta un messaggio (testo o voce) e determina il tipo di dato o correzione."""
    prompt = f"""Analizza questo messaggio di un atleta ciclista e determina cosa vuole fare.
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

REGOLA PRIORITARIA: Se il messaggio contiene "?" oppure inizia con una parola interrogativa (quale, quali, come, quando, perché, cosa, chi, dove, quanto, dimmi, spiegami, parlami), il tipo DEVE essere "coach" o "status" — MAI "meal" o "activity". Una domanda non è mai un input alimentare.

Regole per il tipo:
- meal: SOLO se l'utente dichiara di aver mangiato qualcosa di concreto con quantità o descrizione. Es: "ho mangiato una mela", "pasta 200g al pomodoro", "colazione: yogurt e cereali". NON usare per domande o richieste.
- activity: attività sportiva specifica con durata dichiarata. Es: "ho fatto 1 ora di bici", "corsa 45 minuti". NON usare per domande su attività.
- total_calories_iphone: TOTALE calorie giornata da iPhone/Apple Fitness. Es: "le mie calorie totali sono 2400", "iPhone fitness: 2800 kcal"
- weight: peso corporeo dichiarato. Es: "peso 75.2 kg oggi"
- sleep: ore di sonno dichiarate. Es: "ho dormito 7 ore"
- steps: passi dichiarati. Es: "oggi 9000 passi"
- correction: correzione di un dato precedente. Es: "correggimi l'ultimo pasto", "la mela pesava 150g non 200g"
- status: vuole il riepilogo della giornata. Es: "come sto oggi", "quanto posso ancora mangiare", "status", "riepilogo"
- check_in: risposta al check-in post-sessione. Es: "RPE 7, dormito 6h, stress 4", "8, ero stanco ma è andata bene". Estrai: rpe, condition_pre, condition_during, condition_post, sleep_hours, stress_level.
- pre_condition: descrive come si sente prima di allenarsi, senza registrare attività. Es: "mi sento stanco", "gambe pesanti oggi"
- coach: qualsiasi domanda o richiesta che non sia registrazione dati. Usare per: domande su FTP/zone/potenza ("quale FTP hai usato?", "quali sono le mie zone?", "che potenza devo tenere?"), domande sull'allenamento ("come sto andando?", "ho saltato la sessione"), richieste di analisi, consigli, motivazione. Es COACH: "quale FTP hai usato?", "quali sono le mie zone di potenza?", "come sto andando con l'allenamento?", "perché mi sento stanco?", "cosa devo fare domani?"
- zwo_request: richiesta di generare file .zwo per indoor. Es: "crea una sessione z2 45 minuti", "generami un workout sweetspot di 1 ora"

ESEMPI DI CLASSIFICAZIONE CORRETTA:
✅ "quale FTP hai usato?" → coach (domanda su parametro)
✅ "quali sono le mie zone di potenza?" → coach (domanda su profilo)
✅ "che potenza devo tenere in Z2?" → coach (domanda tecnica)
✅ "ho mangiato una pasta" → meal (dichiarazione cibo consumato)
✅ "ho fatto 1 ora di bici" → activity (attività con durata)
✅ "come sto oggi?" → status (riepilogo giornata)
❌ "quale FTP?" → NON meal
❌ "come sono le mie zone?" → NON meal
"""

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    return json.loads(response.content[0].text)


def _parse_claude_json(response, prompt: str, system: str) -> dict:
    """
    Parsing robusto del JSON da una risposta Claude:
    1. Strip code fence markdown (```json ... ```)
    2. json.loads
    3. Se troncato (stop_reason=max_tokens), secondo tentativo con continuation
    """
    import json

    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rstrip("`").strip()
        return text

    raw = _strip_fences(response.content[0].text)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if response.stop_reason != "max_tokens":
            raise
        # Secondo tentativo: chiediamo a Claude di completare il JSON troncato
        cont = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4000,
            system=system,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response.content[0].text},
                {"role": "user", "content": (
                    "Il JSON è stato troncato. Continua esattamente da dove ti sei "
                    "fermato, senza ripetere niente — solo la parte mancante fino "
                    "alla chiusura dell'oggetto JSON principale."
                )},
            ],
        )
        combined = _strip_fences(raw + cont.content[0].text.strip())
        return json.loads(combined)


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
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_claude_json(response, prompt, SYSTEM_PROMPT)


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
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_claude_json(response, prompt, SYSTEM_PROMPT)


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
