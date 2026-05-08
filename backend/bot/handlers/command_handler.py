from datetime import date
from telegram import Update
from telegram.ext import ContextTypes
from backend.database.client import get_supabase
from backend.config import get_settings

settings = get_settings()


async def get_or_create_user(update: Update) -> str:
    db = get_supabase()
    tg_user = update.effective_user
    telegram_id = str(tg_user.id)

    result = db.table("user_profiles").select("id").eq("telegram_id", telegram_id).execute()
    if result.data:
        return result.data[0]["id"]

    new_user = db.table("user_profiles").insert({
        "telegram_id": telegram_id,
        "name": tg_user.full_name,
        "daily_calorie_goal": settings.default_daily_calorie_goal,
        "protein_goal_g": settings.default_protein_goal,
        "carbs_goal_g": settings.default_carbs_goal,
        "fat_goal_g": settings.default_fat_goal,
    }).execute()
    return new_user.data[0]["id"]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    await update.message.reply_text(
        "👋 *Benvenuto nel tuo Fitness Tracker!*\n\n"
        "Mandami:\n"
        "📝 Testo → 'ho mangiato una pizza'\n"
        "📸 Foto → di cibo, etichette o screenshot Garmin\n"
        "🎙 Vocale → descrivi pasti o attività\n\n"
        "Comandi:\n"
        "/status — situazione attuale + suggerimento\n"
        "/riepilogo — riepilogo di oggi\n"
        "/peso 75.5 — registra il peso\n"
        "/passi 8500 — registra i passi\n"
        "/sonno 7.5 — registra ore di sonno\n"
        "/piano — visualizza piano allenamento\n"
        "/strava — collega Strava\n"
        "/aiuto — tutti i comandi",
        parse_mode="Markdown",
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.services.nutrition_service import get_daily_summary
    user_id = await get_or_create_user(update)
    summary = get_daily_summary(user_id, date.today())

    calorie_balance = summary["calorie_balance"]
    balance_emoji = "🟢" if calorie_balance <= 0 else "🔴"
    balance_text = f"+{calorie_balance}" if calorie_balance > 0 else str(calorie_balance)

    meals_count = len(summary.get("meals", []))
    activities_count = len(summary.get("activities", []))

    reply = (
        f"📅 *Riepilogo di oggi — {date.today().strftime('%d/%m/%Y')}*\n\n"
        f"🍽 *Nutrizione ({meals_count} pasti):*\n"
        f"🔥 Calorie: `{summary['calories_in']} / {summary['calorie_goal']} kcal` {balance_emoji} ({balance_text})\n"
        f"💪 Proteine: `{summary['protein_g']}g / {summary['protein_goal_g']}g`\n"
        f"🌾 Carbs: `{summary['carbs_g']}g / {summary['carbs_goal_g']}g`\n"
        f"🫒 Grassi: `{summary['fat_g']}g / {summary['fat_goal_g']}g`\n\n"
    )

    if activities_count > 0:
        reply += f"🏃 *Attività ({activities_count}):*\n"
        for a in summary.get("activities", []):
            reply += f"  • {a.get('name', 'Attività')}: `{a.get('calories', 0)} kcal`\n"
        reply += f"🔥 Calorie bruciate: `{summary['calories_out']} kcal`\n\n"

    if summary.get("weight_kg"):
        reply += f"⚖️ Peso: `{summary['weight_kg']} kg`\n"
    if summary.get("sleep_hours"):
        reply += f"😴 Sonno: `{summary['sleep_hours']}h`\n"
    if summary.get("steps"):
        reply += f"👟 Passi: `{summary['steps']:,}`\n"

    await update.message.reply_text(reply, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.services.nutrition_service import get_daily_summary
    from backend.services.claude_service import generate_daily_status
    user_id = await get_or_create_user(update)

    await update.message.reply_text("📊 Analizzo la tua giornata...")

    summary = get_daily_summary(user_id, date.today())
    db = get_supabase()
    profile_res = db.table("user_profiles").select("*").eq("id", user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]

    calories_in = summary["calories_in"]
    calories_out = summary["calories_out"]
    calorie_goal = summary["calorie_goal"]
    net = summary["net_calories"]
    remaining_kcal = round(calorie_goal - calories_in)

    remaining_protein = round(profile.get("protein_goal_g", 150) - summary["protein_g"])
    remaining_carbs = round(profile.get("carbs_goal_g", 280) - summary["carbs_g"])
    remaining_fat = round(profile.get("fat_goal_g", 75) - summary["fat_g"])

    # emoji bilancio: verde se in deficit, rosso se in surplus
    bal_emoji = "🟢" if net <= 0 else "🔴"
    cal_out_note = "📱 iPhone Fitness" if summary.get("total_calories_iphone") else "📐 stima BMR"

    def _macro_bar(current, goal):
        pct = min(100, round(current / goal * 100)) if goal else 0
        filled = round(pct / 10)
        return "█" * filled + "░" * (10 - filled) + f" {pct}%"

    reply = (
        f"📊 *Situazione di oggi — {date.today().strftime('%d/%m/%Y')}*\n\n"
        f"🔥 *Calorie*\n"
        f"  Assunte:  `{round(calories_in)} / {calorie_goal} kcal`\n"
        f"  Bruciate: `{round(calories_out)} kcal` ({cal_out_note})\n"
        f"  Bilancio: `{net:+.0f} kcal` {bal_emoji}\n"
        f"  Margine:  `{remaining_kcal} kcal` ancora disponibili\n\n"
        f"💪 *Macro rimanenti*\n"
        f"  Proteine: `{max(0, remaining_protein)}g` rimasti\n"
        f"  {_macro_bar(summary['protein_g'], profile.get('protein_goal_g', 150))}\n"
        f"  Carbs:    `{max(0, remaining_carbs)}g` rimasti\n"
        f"  {_macro_bar(summary['carbs_g'], profile.get('carbs_goal_g', 280))}\n"
        f"  Grassi:   `{max(0, remaining_fat)}g` rimasti\n"
        f"  {_macro_bar(summary['fat_g'], profile.get('fat_goal_g', 75))}\n\n"
    )

    try:
        ai = generate_daily_status(summary, profile)
        reply += f"🍽 *Cosa mangiare ora*\n{ai['suggestion']}\n\n"
        reply += f"🚴 {ai['motivation']}"
    except Exception:
        if remaining_kcal > 0:
            reply += f"🍽 Hai ancora `{remaining_kcal} kcal` disponibili oggi."
        else:
            reply += "⚠️ Hai già raggiunto l'obiettivo calorico di oggi."

    await update.message.reply_text(reply, parse_mode="Markdown")


async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    if not context.args:
        await update.message.reply_text("Uso: /peso 75.5")
        return
    try:
        weight = float(context.args[0].replace(",", "."))
        _upsert_health(user_id, {"weight_kg": weight})
        await update.message.reply_text(f"⚖️ Peso registrato: `{weight} kg`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("Valore non valido. Esempio: /peso 75.5")


async def cmd_steps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    if not context.args:
        await update.message.reply_text("Uso: /passi 8500")
        return
    try:
        steps = int(context.args[0])
        _upsert_health(user_id, {"steps": steps})
        await update.message.reply_text(f"👟 Passi registrati: `{steps:,}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("Valore non valido. Esempio: /passi 8500")


async def cmd_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    if not context.args:
        await update.message.reply_text("Uso: /sonno 7.5")
        return
    try:
        hours = float(context.args[0].replace(",", "."))
        _upsert_health(user_id, {"sleep_hours": hours})
        await update.message.reply_text(f"😴 Sonno registrato: `{hours}h`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("Valore non valido. Esempio: /sonno 7.5")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.services.training_plan_service import get_active_plan, get_plan_sessions
    user_id = await get_or_create_user(update)
    plan = get_active_plan(user_id)

    if not plan:
        await update.message.reply_text(
            "Nessun piano attivo. Usa:\n/nuovopiano <descrizione obiettivo>",
        )
        return

    sessions = get_plan_sessions(plan["id"], from_date=date.today())
    next_sessions = sessions[:5]

    reply = f"🏋️ *{plan['name']}*\n_{plan['goal']}_\n\n*Prossime sessioni:*\n"
    for s in next_sessions:
        status_emoji = {"planned": "📅", "completed": "✅", "skipped": "⏭", "modified": "✏️"}.get(s["status"], "📅")
        reply += f"{status_emoji} {s['scheduled_date']} — {s['title']} ({s['duration_target_min']}min)\n"

    await update.message.reply_text(reply, parse_mode="Markdown")


async def cmd_new_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.services.training_plan_service import create_plan_from_claude
    user_id = await get_or_create_user(update)

    if not context.args:
        await update.message.reply_text("Uso: /nuovopiano voglio correre una 10km in 3 mesi")
        return

    request = " ".join(context.args)
    await update.message.reply_text("🧠 Sto creando il piano con Claude, un momento...")

    try:
        result = create_plan_from_claude(user_id, request)
        await update.message.reply_text(
            f"✅ *Piano creato: {result['name']}*\n"
            f"Sessioni generate: {result['sessions_created']}\n\n"
            f"_{result.get('claude_notes', '')}_\n\n"
            "Usa /piano per vedere le sessioni.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Errore nella creazione del piano: {e}")


async def cmd_strava(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.services.strava_service import get_auth_url
    user_id = await get_or_create_user(update)
    url = get_auth_url(state=user_id)
    await update.message.reply_text(
        f"🚴 Collega Strava:\n{url}\n\nDopo l'autorizzazione le attività verranno sincronizzate automaticamente."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Tutti i comandi:*\n\n"
        "/status — situazione attuale, margine calorie e suggerimento AI\n"
        "/riepilogo — riepilogo nutrizionale di oggi\n"
        "/peso 75.5 — registra peso corporeo\n"
        "/passi 8500 — registra passi giornalieri\n"
        "/sonno 7.5 — registra ore di sonno\n"
        "/piano — piano di allenamento\n"
        "/nuovopiano <obiettivo> — crea piano con AI\n"
        "/strava — collega account Strava\n"
        "/syncstrava — sincronizza attività Strava\n"
        "/aiuto — questo messaggio\n\n"
        "*Input supportati:*\n"
        "📝 Testo → pasti, attività, dati vari\n"
        "📸 Foto → cibo (stima calorie), etichette (legge valori), Garmin (estrae dati)\n"
        "🎙 Vocale → trascrizione automatica\n\n"
        "_Tip foto etichette: aggiungi '150g' nel caption per calcolare la porzione giusta_",
        parse_mode="Markdown",
    )


async def cmd_sync_strava(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.services.strava_service import sync_recent_activities
    user_id = await get_or_create_user(update)
    await update.message.reply_text("🔄 Sincronizzazione Strava in corso...")
    try:
        imported = await sync_recent_activities(user_id, days=14)
        await update.message.reply_text(
            f"✅ Sincronizzate {len(imported)} nuove attività da Strava."
        )
    except Exception as e:
        await update.message.reply_text(f"Errore Strava: {e}")


def _upsert_health(user_id: str, data: dict):
    db = get_supabase()
    today = date.today().isoformat()
    existing = db.table("daily_health").select("id").eq("user_id", user_id).eq("health_date", today).execute()
    payload = {"user_id": user_id, "health_date": today, **data}
    if existing.data:
        db.table("daily_health").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        db.table("daily_health").insert(payload).execute()
