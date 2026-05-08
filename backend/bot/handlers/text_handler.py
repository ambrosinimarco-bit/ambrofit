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
            db.table("activities").insert({
                "user_id": user_id,
                "activity_date": date.today().isoformat(),
                "activity_type": data.get("activity_type", "other"),
                "name": data.get("name", text[:50]),
                "duration_min": data.get("duration_min", 0),
                "distance_km": data.get("distance_km"),
                "notes": text,
                "source": source,
            }).execute()
            await update.message.reply_text(
                f"✅ *Attività registrata:* {data.get('name', 'Attività')}\n"
                f"⏱ `{data.get('duration_min', 0)} min`"
                + (f" · 📍 `{data.get('distance_km')} km`" if data.get("distance_km") else ""),
                parse_mode="Markdown",
            )

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
