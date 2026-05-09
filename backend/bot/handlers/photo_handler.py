import re
from datetime import date
from telegram import Update
from telegram.ext import ContextTypes
from backend.services.claude_service import (
    analyze_food_photo,
    analyze_nutrition_label,
    analyze_garmin_screenshot,
)
from backend.database.client import get_supabase
from backend.bot.handlers.command_handler import get_or_create_user


def _detect_photo_type(caption: str) -> str:
    """Determina il tipo di foto dal caption."""
    if not caption:
        return "food"
    c = caption.lower()
    if any(k in c for k in ["etichetta", "label", "ingredienti", "valori nutrizionali"]):
        return "label"
    if any(k in c for k in ["garmin", "screenshot", "stress", "body battery", "hrv", "sonno"]):
        return "garmin"
    return "food"


def _extract_quantity(caption: str) -> float:
    """Estrae la quantità in grammi dal caption."""
    if not caption:
        return 100.0
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*g", caption, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", "."))
    return 100.0


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    caption = update.message.caption or ""
    photo_type = _detect_photo_type(caption)

    await update.message.reply_text("📸 Sto analizzando la foto...")

    photo = update.message.photo[-1]
    photo_file = await photo.get_file()
    image_bytes = await photo_file.download_as_bytearray()
    image_bytes = bytes(image_bytes)

    db = get_supabase()

    try:
        if photo_type == "garmin":
            result = analyze_garmin_screenshot(image_bytes)
            _save_garmin_data(db, user_id, result)
            reply_text = _format_garmin_reply(result, db, user_id)
            await update.message.reply_text(reply_text, parse_mode="Markdown")

        elif photo_type == "label":
            quantity = _extract_quantity(caption)
            result = analyze_nutrition_label(image_bytes, quantity)
            _save_label_meal(db, user_id, result, quantity)
            await update.message.reply_text(_format_label_reply(result, quantity), parse_mode="Markdown")

        else:
            result = analyze_food_photo(image_bytes, caption)
            _save_food_meal(db, user_id, result)
            await update.message.reply_text(_format_food_reply(result), parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"Errore nell'analisi della foto: {e}")


def _save_food_meal(db, user_id: str, result: dict):
    db.table("meals").insert({
        "user_id": user_id,
        "meal_date": date.today().isoformat(),
        "meal_time": result.get("meal_time", "snack"),
        "name": result.get("meal_name", "Pasto da foto"),
        "calories": result.get("total_calories", 0),
        "protein_g": result.get("total_protein_g", 0),
        "carbs_g": result.get("total_carbs_g", 0),
        "fat_g": result.get("total_fat_g", 0),
        "fiber_g": result.get("total_fiber_g", 0),
        "source": "telegram_photo",
        "notes": result.get("notes", ""),
    }).execute()


def _save_label_meal(db, user_id: str, result: dict, quantity: float):
    per_qty = result.get("per_quantity", {})
    db.table("meals").insert({
        "user_id": user_id,
        "meal_date": date.today().isoformat(),
        "meal_time": "snack",
        "name": result.get("product_name", "Prodotto da etichetta"),
        "calories": per_qty.get("calories", 0),
        "protein_g": per_qty.get("protein_g", 0),
        "carbs_g": per_qty.get("carbs_g", 0),
        "fat_g": per_qty.get("fat_g", 0),
        "fiber_g": per_qty.get("fiber_g", 0),
        "quantity_g": quantity,
        "source": "telegram_label",
    }).execute()


def _save_garmin_data(db, user_id: str, result: dict):
    target_date = result.get("date") or date.today().isoformat()
    screen_type = result.get("screen_type", "health")

    # Salva dati salute se presenti
    has_health_data = any(result.get(k) for k in [
        "body_battery_end", "body_battery_start", "stress_score",
        "hrv_ms", "resting_hr", "sleep_hours", "steps",
        "calories_active", "calories_total",
    ])
    if has_health_data or screen_type in ("health", "mixed"):
        existing = db.table("daily_health").select("id")\
            .eq("user_id", user_id).eq("health_date", target_date).execute()

        health_data = {
            "user_id": user_id,
            "health_date": target_date,
            "body_battery": result.get("body_battery_end") or result.get("body_battery_start"),
            "stress_score": result.get("stress_score"),
            "hrv_ms": result.get("hrv_ms"),
            "resting_hr": result.get("resting_hr"),
            "sleep_hours": result.get("sleep_hours"),
            "steps": result.get("steps"),
            "notes": result.get("raw_text", "")[:500],
        }
        health_data = {k: v for k, v in health_data.items() if v is not None}

        if existing.data:
            db.table("daily_health").update(health_data).eq("id", existing.data[0]["id"]).execute()
        else:
            db.table("daily_health").insert(health_data).execute()

    # Salva come attività se ci sono dati di potenza/attività ciclistica
    has_activity_data = any(result.get(k) for k in [
        "avg_power_w", "normalized_power_w", "avg_hr_bpm", "duration_min",
    ])
    if screen_type in ("activity", "mixed") or has_activity_data:
        activity_name = result.get("activity_name") or "Attività Garmin"
        duration = result.get("duration_min") or 0
        db.table("activities").insert({
            "user_id": user_id,
            "activity_date": target_date,
            "activity_type": "ride",
            "name": activity_name,
            "duration_min": float(duration),
            "distance_km": result.get("distance_km"),
            "elevation_m": result.get("elevation_m"),
            "avg_heart_rate": result.get("avg_hr_bpm"),
            "max_heart_rate": result.get("max_hr_bpm"),
            "avg_power_w": result.get("avg_power_w"),
            "normalized_power_w": result.get("normalized_power_w"),
            "avg_cadence_rpm": result.get("avg_cadence_rpm"),
            "tss": result.get("tss"),
            "source": "garmin_screenshot",
            "notes": result.get("raw_text", "")[:500],
        }).execute()


def _get_coaching_comment(result: dict, profile: dict) -> str:
    """Genera un commento coaching basato sui dati Garmin e il profilo utente."""
    avg_power = result.get("avg_power_w")
    if not avg_power:
        return ""

    ftp = profile.get("ftp_watts") or 0
    z2_max = profile.get("power_zone_2_max") or 162
    ftp_val = ftp if ftp else 200

    if avg_power < z2_max:
        comment = f"Buona sessione Z2 ({avg_power}W media) — ottimo per costruire la base aerobica."
    elif avg_power >= ftp_val:
        comment = f"Sessione intensa ad alta intensità ({avg_power}W media, vicino o sopra FTP) — monitora il recupero."
    else:
        comment = f"Sessione a intensità moderata ({avg_power}W media) — zona di sviluppo."

    if result.get("avg_cadence_rpm"):
        cad = result["avg_cadence_rpm"]
        cad_min = profile.get("target_cadence_min") or 85
        cad_max = profile.get("target_cadence_max") or 95
        if cad < cad_min:
            comment += f" Cadenza {cad}rpm un po' bassa (target {cad_min}-{cad_max}rpm)."
        elif cad > cad_max:
            comment += f" Cadenza {cad}rpm alta — ottimo se era pianificato."
        else:
            comment += f" Cadenza {cad}rpm nel target."

    return comment


def _format_food_reply(result: dict) -> str:
    confidence_emoji = {"high": "✅", "medium": "⚠️", "low": "❓"}.get(result.get("confidence", "medium"), "⚠️")
    items = "\n".join(f"  • {i['name']}: ~{i['calories']} kcal" for i in result.get("items", []))
    return (
        f"{confidence_emoji} *{result.get('meal_name', 'Pasto identificato')}*\n\n"
        f"{items}\n\n"
        f"📊 *Totali:*\n"
        f"🔥 Calorie: `{result.get('total_calories', 0)} kcal`\n"
        f"💪 Proteine: `{result.get('total_protein_g', 0)}g`\n"
        f"🌾 Carbs: `{result.get('total_carbs_g', 0)}g`\n"
        f"🫒 Grassi: `{result.get('total_fat_g', 0)}g`\n"
        f"_Nota: {result.get('notes', '')}_"
    )


def _format_label_reply(result: dict, quantity: float) -> str:
    per_qty = result.get("per_quantity", {})
    per_100 = result.get("per_100g", {})
    return (
        f"🏷 *{result.get('product_name', 'Prodotto')}* ({quantity}g)\n\n"
        f"📊 *Per {quantity}g:*\n"
        f"🔥 Calorie: `{per_qty.get('calories', 0)} kcal`\n"
        f"💪 Proteine: `{per_qty.get('protein_g', 0)}g`\n"
        f"🌾 Carbs: `{per_qty.get('carbs_g', 0)}g`\n"
        f"🫒 Grassi: `{per_qty.get('fat_g', 0)}g`\n"
        f"🌿 Fibre: `{per_qty.get('fiber_g', 0)}g`\n\n"
        f"_Per 100g: {per_100.get('calories', 0)} kcal_\n"
        f"_Ingredienti: {result.get('ingredients_summary', 'n/d')}_"
    )


def _format_garmin_reply(result: dict, db=None, user_id: str = "") -> str:
    screen_type = result.get("screen_type", "health")
    lines = ["📱 *Dati Garmin rilevati:*\n"]

    # Dati salute
    if result.get("body_battery_end"):
        lines.append(f"🔋 Body Battery: `{result['body_battery_end']}`")
    if result.get("stress_score"):
        lines.append(f"😤 Stress: `{result['stress_score']}`")
    if result.get("hrv_ms"):
        lines.append(f"💓 HRV: `{result['hrv_ms']} ms`")
    if result.get("resting_hr"):
        lines.append(f"❤️ FC riposo: `{result['resting_hr']} bpm`")
    if result.get("sleep_hours"):
        lines.append(f"😴 Sonno: `{result['sleep_hours']}h`")
    if result.get("steps"):
        lines.append(f"👟 Passi: `{result['steps']:,}`")

    # Dati attività ciclistica
    if screen_type in ("activity", "mixed") or result.get("avg_power_w"):
        if result.get("activity_name"):
            lines.append(f"\n🚴 *Attività:* {result['activity_name']}")
        if result.get("duration_min"):
            lines.append(f"⏱ Durata: `{result['duration_min']} min`")
        if result.get("distance_km"):
            lines.append(f"📍 Distanza: `{result['distance_km']} km`")
        if result.get("avg_power_w"):
            lines.append(f"⚡ Potenza media: `{result['avg_power_w']} W`")
        if result.get("normalized_power_w"):
            lines.append(f"📊 NP: `{result['normalized_power_w']} W`")
        if result.get("avg_cadence_rpm"):
            lines.append(f"🔄 Cadenza media: `{result['avg_cadence_rpm']} rpm`")
        if result.get("avg_hr_bpm"):
            lines.append(f"❤️ FC media: `{result['avg_hr_bpm']} bpm`")
        if result.get("elevation_m"):
            lines.append(f"⛰ Dislivello: `{result['elevation_m']} m`")
        if result.get("tss"):
            lines.append(f"📈 TSS: `{result['tss']}`")

    lines.append("\n✅ Dati salvati!")

    # Commento coaching se ci sono dati di potenza e db/user_id disponibili
    if db and user_id and result.get("avg_power_w"):
        try:
            profile_res = db.table("user_profiles").select(
                "ftp_watts,power_zone_2_max,target_cadence_min,target_cadence_max"
            ).eq("id", user_id).limit(1).execute()
            profile = (profile_res.data or [{}])[0]
            coaching = _get_coaching_comment(result, profile)
            if coaching:
                lines.append(f"\n🎯 *Coach:* {coaching}")
        except Exception:
            pass

    return "\n".join(lines)
