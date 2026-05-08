"""Coach service: risponde a domande di coaching usando il contesto completo dell'utente."""
import anthropic
from datetime import date, timedelta
from backend.config import get_settings
from backend.database.client import get_supabase

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def get_coach_response(user_id: str, message: str) -> str:
    """Genera una risposta di coaching contestuale per l'utente."""
    db = get_supabase()

    # 1. Fetch profilo utente
    profile_res = db.table("user_profiles").select("*").eq("id", user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]

    # 2. Fetch ultime 7 attività
    since = (date.today() - timedelta(days=7)).isoformat()
    acts_res = db.table("activities").select("*").eq("user_id", user_id)\
        .gte("activity_date", since).order("activity_date", desc=True).limit(10).execute()
    activities = acts_res.data or []

    # 3. Fetch summary di oggi
    today_str = date.today().isoformat()
    meals_res = db.table("meals").select("calories,protein_g,carbs_g,fat_g")\
        .eq("user_id", user_id).eq("meal_date", today_str).execute()
    meals = meals_res.data or []
    calories_in = sum(m.get("calories", 0) or 0 for m in meals)

    health_res = db.table("daily_health").select("total_calories_iphone,weight_kg")\
        .eq("user_id", user_id).eq("health_date", today_str).limit(1).execute()
    health_today = (health_res.data or [{}])[0]
    calories_out = health_today.get("total_calories_iphone") or 0

    # 4. Costruisci system prompt
    ftp = profile.get("ftp_watts")
    z1 = profile.get("power_zone_1_max") or 121
    z2 = profile.get("power_zone_2_max") or 162
    z3 = profile.get("power_zone_3_max") or 182
    z4 = profile.get("power_zone_4_max") or 192
    cad_min = profile.get("target_cadence_min") or 85
    cad_max = profile.get("target_cadence_max") or 95
    medical = profile.get("medical_notes") or "nessuna nota medica"

    if ftp:
        system_prompt = (
            f"Sei il coach personale di Marco, ciclista di 53 anni con FTP {ftp}W.\n"
            f"Note mediche: {medical}\n"
            f"Zone di potenza: Z1 <{z1}W | Z2 {z1}-{z2}W | Z3 {z2}-{z3}W | Z4 SS {z3}-{z4}W | Z5 {z4}W+\n"
            f"Cadenza target: {cad_min}-{cad_max} rpm (difficoltà sulle salite >6-7%)\n"
            f"Obiettivo: gran fondo ciclistiche, ricomposizione corporea, stagione multi-evento\n"
            f"Disponibilità: 2-3 sessioni/settimana, lungo nel weekend\n\n"
            f"Rispondi in italiano, in modo diretto e pratico. Massimo 3-4 paragrafi.\n"
            f"Tieni sempre in conto i vincoli medici nelle raccomandazioni."
        )
    else:
        system_prompt = (
            "Sei il coach personale di Marco, ciclista di 53 anni.\n"
            f"Note mediche: {medical}\n"
            "Obiettivo: gran fondo ciclistiche, ricomposizione corporea, stagione multi-evento\n"
            "Disponibilità: 2-3 sessioni/settimana, lungo nel weekend\n\n"
            "Rispondi in italiano, in modo diretto e pratico. Massimo 3-4 paragrafi.\n"
            "Tieni sempre in conto i vincoli medici nelle raccomandazioni."
        )

    # 5. Costruisci contesto attività
    acts_summary = ""
    if activities:
        lines = []
        for a in activities:
            parts = [f"- {a.get('activity_date', '')} {a.get('name', 'Attività')} ({a.get('activity_type', 'other')})"]
            if a.get("duration_min"):
                parts.append(f"{a['duration_min']}min")
            if a.get("distance_km"):
                parts.append(f"{a['distance_km']}km")
            if a.get("rpe"):
                parts.append(f"RPE {a['rpe']}/10")
            if a.get("physical_notes"):
                parts.append(f"Note: {a['physical_notes']}")
            lines.append(" | ".join(parts))
        acts_summary = "\n".join(lines)
    else:
        acts_summary = "Nessuna attività registrata negli ultimi 7 giorni."

    user_message = (
        f"Contesto oggi ({today_str}):\n"
        f"- Calorie assunte: {round(calories_in)} kcal\n"
        f"- Calorie bruciate (iPhone): {round(calories_out)} kcal\n\n"
        f"Attività ultimi 7 giorni:\n{acts_summary}\n\n"
        f"Messaggio dell'utente: {message}"
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text
