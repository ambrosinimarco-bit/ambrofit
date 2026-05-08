import io
import re
from datetime import date
from telegram import Update
from telegram.ext import ContextTypes
from backend.services.claude_service import analyze_food_text, analyze_voice_transcript
from backend.database.client import get_supabase
from backend.bot.handlers.command_handler import get_or_create_user


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    text = update.message.text.strip()
    await update.message.reply_text("Sto analizzando il messaggio...")
    await dispatch_message(update, context, user_id, text, source="telegram_text")


async def dispatch_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str,
    text: str,
    source: str = "telegram_text",
) -> None:
    """Classifica il testo (o trascritto vocale) e smista all'azione corretta."""
    try:
        classification = analyze_voice_transcript(text)
        data_type = classification.get("type", "meal")
        data = classification.get("data", {})
        db = get_supabase()

        if data_type == "status":
            from backend.bot.handlers.command_handler import cmd_status
            await cmd_status(update, context)

        elif data_type in ("total_calories_iphone", "calories_burned"):
            calories = data.get("total_calories_iphone") or data.get("calories", 0)
            _upsert_health(db, user_id, {"total_calories_iphone": int(calories)})
            await update.message.reply_text(
                f"📱 *Calorie totali giornata registrate*\n`{int(calories)} kcal`",
                parse_mode="Markdown",
            )

        elif data_type == "correction":
            await _handle_correction(update, db, user_id, data, text)

        elif data_type == "activity":
            result = db.table("activities").insert({
                "user_id": user_id,
                "activity_date": date.today().isoformat(),
                "activity_type": data.get("activity_type", "other"),
                "name": data.get("name", text[:50]),
                "duration_min": data.get("duration_min", 0),
                "distance_km": data.get("distance_km"),
                "notes": text,
                "source": source,
            }).execute()
            activity_msg = (
                f"✅ *Attività registrata:* {data.get('name', 'Attività')}\n"
                f"⏱ `{data.get('duration_min', 0)} min`"
                + (f" · 📍 `{data.get('distance_km')} km`" if data.get("distance_km") else "")
            )
            activity_msg += (
                "\n\n📊 *Check-in:* Come ti sei sentito? Rispondimi con un voto da 1 a 10 "
                "e segnala eventuali problemi fisici (es. '8, tutto ok' o '6, fastidio all\'inguine')"
            )
            await update.message.reply_text(activity_msg, parse_mode="Markdown")

        elif data_type == "check_in":
            await _handle_check_in(update, db, user_id, data)

        elif data_type == "coach":
            from backend.services.coach_service import get_coach_response
            await update.message.reply_text("🧠 Sto elaborando la risposta del coach...")
            response_text = await get_coach_response(user_id, text)
            await update.message.reply_text(response_text)

        elif data_type == "zwo_request":
            await _handle_zwo_request(update, db, user_id, text)

        elif data_type == "weight":
            _upsert_health(db, user_id, {"weight_kg": data.get("weight_kg")})
            await update.message.reply_text(f"⚖️ Peso registrato: `{data.get('weight_kg')} kg`", parse_mode="Markdown")

        elif data_type == "sleep":
            _upsert_health(db, user_id, {"sleep_hours": data.get("sleep_hours")})
            await update.message.reply_text(f"😴 Sonno registrato: `{data.get('sleep_hours')}h`", parse_mode="Markdown")

        elif data_type == "steps":
            _upsert_health(db, user_id, {"steps": data.get("steps")})
            await update.message.reply_text(f"👟 Passi registrati: `{data.get('steps'):,}`", parse_mode="Markdown")

        else:
            # Pasto (meal o general) — analisi nutrizionale dettagliata
            result = analyze_food_text(text)
            db.table("meals").insert({
                "user_id": user_id,
                "meal_date": date.today().isoformat(),
                "meal_time": result.get("meal_time", "snack"),
                "name": result.get("meal_name", text[:50]),
                "calories": result.get("total_calories", 0),
                "protein_g": result.get("total_protein_g", 0),
                "carbs_g": result.get("total_carbs_g", 0),
                "fat_g": result.get("total_fat_g", 0),
                "fiber_g": result.get("total_fiber_g", 0),
                "notes": text,
                "source": source,
            }).execute()

            confidence_emoji = {"high": "✅", "medium": "⚠️", "low": "❓"}.get(result.get("confidence", "medium"), "⚠️")
            items_text = "\n".join(
                f"  • {i['name']}: {i['calories']} kcal" for i in result.get("items", [])
            )
            reply = (
                f"{confidence_emoji} *{result.get('meal_name', 'Pasto registrato')}*\n\n"
                f"{items_text}\n\n"
                f"📊 *Totali:*\n"
                f"🔥 Calorie: `{result.get('total_calories', 0)} kcal`\n"
                f"💪 Proteine: `{result.get('total_protein_g', 0)}g`\n"
                f"🌾 Carboidrati: `{result.get('total_carbs_g', 0)}g`\n"
                f"🫒 Grassi: `{result.get('total_fat_g', 0)}g`\n"
            )
            await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(
            f"Non ho capito il messaggio. Prova a essere più specifico.\nErrore: {e}"
        )


async def _handle_check_in(update, db, user_id: str, data: dict) -> None:
    """Aggiorna l'ultima attività del giorno senza check-in con RPE e note fisiche."""
    rpe = data.get("rpe")
    physical_notes = data.get("physical_notes") or ""

    # Trova l'ultima attività del giorno senza check-in
    today = date.today().isoformat()
    result = db.table("activities").select("*").eq("user_id", user_id)\
        .eq("activity_date", today).eq("check_in_done", False)\
        .order("created_at", desc=True).limit(1).execute()

    if not result.data:
        # Prova anche senza il filtro check_in_done (colonna potrebbe non esistere ancora)
        result = db.table("activities").select("*").eq("user_id", user_id)\
            .eq("activity_date", today)\
            .order("created_at", desc=True).limit(1).execute()

    if not result.data:
        await update.message.reply_text(
            "Non trovo attività registrate oggi da aggiornare con il check-in. "
            "Registra prima un'attività!"
        )
        return

    activity = result.data[0]
    update_data = {"check_in_done": True}
    if rpe is not None:
        update_data["rpe"] = int(rpe)
    if physical_notes:
        update_data["physical_notes"] = physical_notes

    db.table("activities").update(update_data).eq("id", activity["id"]).execute()

    # Risposta coaching basata su RPE
    if rpe is not None:
        rpe_int = int(rpe)
        if rpe_int <= 6:
            coaching_comment = "Bel recupero, hai gestito bene il carico."
        elif rpe_int <= 8:
            coaching_comment = "Perfetto range per l'allenamento base."
        else:
            coaching_comment = "Sessione impegnativa, monitora il recupero nelle prossime 48h."
        reply = (
            f"✅ *Check-in registrato per:* {activity.get('name', 'Attività')}\n"
            f"📊 RPE: `{rpe}/10`"
        )
        if physical_notes:
            reply += f"\n📝 Note: _{physical_notes}_"
        reply += f"\n\n🎯 {coaching_comment}"
    else:
        reply = f"✅ *Check-in registrato per:* {activity.get('name', 'Attività')}"
        if physical_notes:
            reply += f"\n📝 Note: _{physical_notes}_"

    await update.message.reply_text(reply, parse_mode="Markdown")


async def _handle_zwo_request(update, db, user_id: str, text: str) -> None:
    """Genera e invia un file .zwo via Telegram."""
    from backend.services.claude_service import plan_zwo_workout
    from backend.services.zwo_service import generate_zwo_xml

    # Fetch profilo utente
    profile_res = db.table("user_profiles").select("ftp_watts,weight_kg").eq("id", user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]
    ftp = profile.get("ftp_watts") or 200
    weight_kg = profile.get("weight_kg") or 75.0

    await update.message.reply_text("⚙️ Sto pianificando il workout con Claude AI...")

    workout = plan_zwo_workout(text, ftp)
    xml_content = generate_zwo_xml(workout, ftp, weight_kg)

    # Nome file sicuro
    workout_name = workout.get("name", "Workout")
    safe_name = re.sub(r'[^\w\s-]', '', workout_name).strip().replace(' ', '_')
    if not safe_name:
        safe_name = "Workout"

    # Invia file .zwo
    file_bytes = io.BytesIO(xml_content.encode('utf-8'))
    file_bytes.name = f"{safe_name}.zwo"
    await update.message.reply_document(
        document=file_bytes,
        filename=f"{safe_name}.zwo",
    )

    # Invia descrizione
    description = workout.get("description", "")
    segments = workout.get("segments", [])
    total_min = sum(float(s.get("duration_min", 0)) for s in segments)

    reply = (
        f"🚴 *{workout_name}*\n"
        f"⏱ Durata totale: `{int(total_min)} minuti`\n\n"
    )
    if description:
        reply += f"_{description}_\n\n"

    reply += "*Struttura:*\n"
    for seg in segments:
        seg_type = seg.get("type", "")
        dur = seg.get("duration_min", 0)
        if seg_type == "IntervalsT":
            repeat = seg.get("repeat", 4)
            on_min = seg.get("on_duration_min", 1)
            off_min = seg.get("off_duration_min", 1)
            on_pwr = round(float(seg.get("on_power", 1.0)) * ftp)
            off_pwr = round(float(seg.get("off_power", 0.55)) * ftp)
            reply += f"  • Intervalli: {repeat}×{on_min}min @ ~{on_pwr}W / {off_min}min @ ~{off_pwr}W\n"
        elif seg_type == "Warmup":
            reply += f"  • Riscaldamento: {dur}min\n"
        elif seg_type == "Cooldown":
            reply += f"  • Defaticamento: {dur}min\n"
        elif seg_type == "SteadyState":
            pwr = round(float(seg.get("power", 0.70)) * ftp)
            reply += f"  • Steady state: {dur}min @ ~{pwr}W\n"

    await update.message.reply_text(reply, parse_mode="Markdown")


def _upsert_health(db, user_id: str, data: dict):
    today = date.today().isoformat()
    existing = db.table("daily_health").select("id").eq("user_id", user_id).eq("health_date", today).execute()
    payload = {"user_id": user_id, "health_date": today, **data}
    if existing.data:
        db.table("daily_health").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        db.table("daily_health").insert(payload).execute()


async def _handle_correction(update, db, user_id: str, data: dict, original_text: str):
    entity_type = data.get("entity_type", "meal")
    corrections = data.get("corrections", {})
    description = data.get("description", "")

    if entity_type == "meal":
        result = db.table("meals").select("*").eq("user_id", user_id)\
            .order("created_at", desc=True).limit(5).execute()
        records = result.data or []
        if not records:
            await update.message.reply_text("Non trovo pasti recenti da correggere.")
            return
        target = records[0]
        if description:
            for r in records:
                if any(word.lower() in (r.get("name") or "").lower() for word in description.split()):
                    target = r
                    break
        update_data = {k: v for k, v in corrections.items()
                       if k in {"calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "quantity_g", "name", "meal_time"}}
        if not update_data:
            await update.message.reply_text(
                f"Ho trovato: *{target['name']}* ({target['calories']} kcal)\nDimmi cosa vuoi correggere.",
                parse_mode="Markdown"
            )
            return
        db.table("meals").update(update_data).eq("id", target["id"]).execute()
        changes = ", ".join(f"{k}={v}" for k, v in update_data.items())
        await update.message.reply_text(
            f"Corretto *{target['name']}*:\n{changes}",
            parse_mode="Markdown"
        )

    elif entity_type == "activity":
        result = db.table("activities").select("*").eq("user_id", user_id)\
            .order("created_at", desc=True).limit(5).execute()
        records = result.data or []
        if not records:
            await update.message.reply_text("Non trovo attività recenti da correggere.")
            return
        target = records[0]
        update_data = {k: v for k, v in corrections.items()
                       if k in {"calories", "duration_min", "distance_km", "elevation_m", "name", "activity_type"}}
        if not update_data:
            await update.message.reply_text(
                f"Ho trovato: *{target['name']}* ({target.get('duration_min', 0)} min)\nDimmi cosa vuoi correggere.",
                parse_mode="Markdown"
            )
            return
        db.table("activities").update(update_data).eq("id", target["id"]).execute()
        changes = ", ".join(f"{k}={v}" for k, v in update_data.items())
        await update.message.reply_text(f"Attività corretta: {changes}", parse_mode="Markdown")

    elif entity_type == "weight":
        new_weight = corrections.get("weight_kg")
        if new_weight:
            _upsert_health(db, user_id, {"weight_kg": new_weight})
            await update.message.reply_text(f"Peso corretto: `{new_weight} kg`", parse_mode="Markdown")
        else:
            await update.message.reply_text("Non ho capito il nuovo valore del peso.")

    else:
        await update.message.reply_text(
            "Non riesco a correggere automaticamente questo dato. Usa la dashboard web per modificarlo."
        )
