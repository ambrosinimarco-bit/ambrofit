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
            await update.message.reply_text(_format_garmin_reply(result), parse_mode="Markdown")

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
    existing = db.table("daily_health").select("id").eq("user_id", user_id).eq("health_date", target_date).execute()

    data = {
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
    data = {k: v for k, v in data.items() if v is not None}

    if existing.data:
        db.table("daily_health").update(data).eq("id", existing.data[0]["id"]).execute()
    else:
        db.table("daily_health").insert(data).execute()


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


def _format_garmin_reply(result: dict) -> str:
    lines = ["📱 *Dati Garmin rilevati:*\n"]
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
    lines.append("\n✅ Dati salvati!")
    return "\n".join(lines)
