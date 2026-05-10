import asyncio
import logging
import re
from datetime import date, timedelta

print("photo_handler v4 loaded (immediate, no buffer)", flush=True)
logger = logging.getLogger(__name__)

from telegram import Update
from telegram.ext import ContextTypes
from backend.services.claude_service import (
    analyze_food_photo,
    analyze_nutrition_label,
    analyze_garmin_screenshots_batch,
    classify_photo_type,
    generate_activity_report,
)
from backend.database.client import get_supabase
from backend.bot.handlers.command_handler import get_or_create_user

_GARMIN_KEYWORDS = {
    "garmin", "screenshot", "stress", "body battery", "hrv", "sonno",
    "dati", "attività", "attivita", "bpm", "potenza", "watt", "dislivello",
}
_LABEL_KEYWORDS = {"etichetta", "label", "ingredienti", "valori nutrizionali"}


def _detect_photo_type_from_caption(caption: str) -> str | None:
    if not caption:
        return None
    c = caption.lower()
    if any(k in c for k in _LABEL_KEYWORDS):
        return "label"
    if any(k in c for k in _GARMIN_KEYWORDS):
        return "garmin"
    return None


def _extract_quantity(caption: str) -> float:
    if not caption:
        return 100.0
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*g", caption, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", "."))
    return 100.0


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    caption = update.message.caption or ""
    print(f"[photo] received from user={user_id} caption={caption!r}", flush=True)

    photo = update.message.photo[-1]
    photo_file = await photo.get_file()
    image_bytes = bytes(await photo_file.download_as_bytearray())
    print(f"[photo] downloaded {len(image_bytes)} bytes", flush=True)

    photo_type = _detect_photo_type_from_caption(caption)
    if photo_type is None:
        await update.message.reply_text("📸 Sto analizzando la foto...")
        print("[photo] caption ambiguous — calling Claude Haiku for classification", flush=True)
        photo_type = await asyncio.to_thread(classify_photo_type, image_bytes)
    print(f"[photo] classified as: {photo_type}", flush=True)

    db = get_supabase()
    try:
        if photo_type == "garmin":
            await update.message.reply_text("📸 Analizzo lo screenshot Garmin...")
            print(f"[photo] calling Claude for garmin analysis (user={user_id})", flush=True)
            result = await asyncio.to_thread(analyze_garmin_screenshots_batch, [image_bytes])
            print(f"[photo] Claude response received: screen_type={result.get('screen_type')}", flush=True)
            print(f"[photo] saving to DB (user={user_id})", flush=True)
            activity_id = _save_garmin_data(db, user_id, result)
            print(f"[photo] DB saved, activity_id={activity_id}", flush=True)
            await update.message.reply_text(_format_garmin_reply(result, db, user_id), parse_mode="Markdown")
            if result.get("avg_power_w") or result.get("duration_min"):
                await _send_activity_report(update, db, user_id, result, activity_id)

        elif photo_type == "label":
            await update.message.reply_text("📸 Sto analizzando la foto...")
            quantity = _extract_quantity(caption)
            result = await asyncio.to_thread(analyze_nutrition_label, image_bytes, quantity)
            _save_label_meal(db, user_id, result, quantity)
            await update.message.reply_text(_format_label_reply(result, quantity), parse_mode="Markdown")

        else:
            await update.message.reply_text("📸 Sto analizzando la foto...")
            result = await asyncio.to_thread(analyze_food_photo, image_bytes, caption)
            _save_food_meal(db, user_id, result)
            await update.message.reply_text(_format_food_reply(result), parse_mode="Markdown")

    except Exception as e:
        logger.exception("handle_photo error for user=%s: %s", user_id, e)
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
    per_100 = result.get("per_100g", {})
    product_name = result.get("product_name", "Prodotto da etichetta")
    db.table("meals").insert({
        "user_id": user_id,
        "meal_date": date.today().isoformat(),
        "meal_time": "snack",
        "name": product_name,
        "calories": per_qty.get("calories", 0),
        "protein_g": per_qty.get("protein_g", 0),
        "carbs_g": per_qty.get("carbs_g", 0),
        "fat_g": per_qty.get("fat_g", 0),
        "fiber_g": per_qty.get("fiber_g", 0),
        "quantity_g": quantity,
        "source": "telegram_label",
    }).execute()

    # Save to personal food database using per-100g values from the label
    if per_100 and per_100.get("calories"):
        from backend.services.food_service import upsert_food_item
        upsert_food_item(
            db, user_id, product_name, "foto_etichetta",
            calories_per_100g=per_100.get("calories"),
            protein_per_100g=per_100.get("protein_g"),
            carbs_per_100g=per_100.get("carbs_g"),
            fat_per_100g=per_100.get("fat_g"),
            fiber_per_100g=per_100.get("fiber_g"),
        )


def _save_garmin_data(db, user_id: str, result: dict) -> str | None:
    """Merge Garmin screenshot data into today's activity.

    Priority: strava activity for same day → existing garmin activity → insert new.
    When a Strava activity is found, any garmin_screenshot duplicates are deleted.
    """
    target_date = result.get("date") or date.today().isoformat()
    screen_type = result.get("screen_type", "health")

    # ── daily_health upsert ───────────────────────────────────────────
    has_health_data = any(result.get(k) for k in [
        "body_battery_end", "body_battery_start", "stress_score",
        "hrv_ms", "resting_hr", "sleep_hours", "steps",
        "calories_active", "calories_total",
    ])
    if has_health_data or screen_type in ("health", "mixed"):
        existing = db.table("daily_health").select("id")\
            .eq("user_id", user_id).eq("health_date", target_date).execute()
        health_data = {k: v for k, v in {
            "user_id": user_id,
            "health_date": target_date,
            "body_battery": result.get("body_battery_end") or result.get("body_battery_start"),
            "stress_score": result.get("stress_score"),
            "hrv_ms": result.get("hrv_ms"),
            "resting_hr": result.get("resting_hr"),
            "sleep_hours": result.get("sleep_hours"),
            "steps": result.get("steps"),
        }.items() if v is not None}
        if existing.data:
            db.table("daily_health").update(health_data).eq("id", existing.data[0]["id"]).execute()
        else:
            db.table("daily_health").insert(health_data).execute()

    # ── activity merge ────────────────────────────────────────────────
    has_activity_data = any(result.get(k) for k in [
        "avg_power_w", "normalized_power_w", "avg_hr_bpm", "duration_min",
    ])
    activity_id: str | None = None
    if not (screen_type in ("activity", "mixed") or has_activity_data):
        return activity_id

    garmin_fields = {k: v for k, v in {
        "duration_min":        float(result.get("duration_min") or 0) or None,
        "distance_km":         result.get("distance_km"),
        "elevation_m":         result.get("elevation_m"),
        "avg_heart_rate":      result.get("avg_hr_bpm"),
        "max_heart_rate":      result.get("max_hr_bpm"),
        "avg_power_w":         result.get("avg_power_w"),
        "normalized_power_w":  result.get("normalized_power_w"),
        "avg_cadence_rpm":     result.get("avg_cadence_rpm"),
        "tss":                 result.get("tss"),
    }.items() if v is not None}

    # Priority 1: Strava activity on the same day
    strava = db.table("activities").select("id")\
        .eq("user_id", user_id).eq("activity_date", target_date)\
        .eq("source", "strava").limit(1).execute()

    if strava.data:
        activity_id = strava.data[0]["id"]
        db.table("activities").update(garmin_fields).eq("id", activity_id).execute()
        logger.info("garmin: merged into strava activity_id=%s date=%s user=%s",
                    activity_id, target_date, user_id)

        # Remove any garmin_screenshot duplicates for this day
        dupes = db.table("activities").select("id")\
            .eq("user_id", user_id).eq("activity_date", target_date)\
            .eq("source", "garmin_screenshot").execute()
        if dupes.data:
            for d in dupes.data:
                db.table("activities").delete().eq("id", d["id"]).execute()
            logger.info("garmin: removed %d stale garmin_screenshot duplicate(s) for date=%s user=%s",
                        len(dupes.data), target_date, user_id)
        return activity_id

    # Priority 2: existing garmin activity on the same day
    garmin_existing = db.table("activities").select("id")\
        .eq("user_id", user_id).eq("activity_date", target_date)\
        .in_("source", ["garmin_screenshot", "garmin"]).limit(1).execute()

    if garmin_existing.data:
        activity_id = garmin_existing.data[0]["id"]
        db.table("activities").update(garmin_fields).eq("id", activity_id).execute()
        logger.info("garmin: updated garmin activity_id=%s user=%s", activity_id, user_id)
        return activity_id

    # Priority 3: insert new
    res = db.table("activities").insert({
        "user_id": user_id,
        "activity_date": target_date,
        "source": "garmin_screenshot",
        "activity_type": "ride",
        "name": result.get("activity_name") or "Attività Garmin",
        **garmin_fields,
    }).execute()
    if res.data:
        activity_id = res.data[0]["id"]
        logger.info("garmin: inserted new activity_id=%s user=%s", activity_id, user_id)

    return activity_id


async def _send_activity_report(
    update: Update,
    db,
    user_id: str,
    garmin_data: dict,
    activity_id: str | None,
) -> None:
    try:
        profile_res = db.table("user_profiles").select(
            "ftp_watts,weight_kg,coaching_notes"
        ).eq("id", user_id).limit(1).execute()
        profile = (profile_res.data or [{}])[0]
        ftp = int(profile.get("ftp_watts") or 202)

        since = (date.today() - timedelta(days=14)).isoformat()
        recent_res = db.table("activities").select(
            "activity_date,name,duration_min,avg_power_w,normalized_power_w,tss"
        ).eq("user_id", user_id).gte("activity_date", since)\
            .order("activity_date", desc=True).limit(10).execute()
        recent_acts = recent_res.data or []

        await update.message.reply_text("🔄 Sto elaborando il report di performance...")
        report = await asyncio.to_thread(generate_activity_report, garmin_data, recent_acts, profile, ftp)
        await update.message.reply_text(report, parse_mode="Markdown")

        target_id = activity_id
        if not target_id:
            today = date.today().isoformat()
            res = db.table("activities").select("id")\
                .eq("user_id", user_id).eq("activity_date", today)\
                .order("created_at", desc=True).limit(1).execute()
            if res.data:
                target_id = res.data[0]["id"]

        if target_id:
            upd = db.table("activities").update({"coaching_notes": report})\
                .eq("id", target_id).execute()
            if upd.data:
                logger.info("coaching_notes saved → activity_id=%s", target_id)
            else:
                logger.warning("coaching_notes UPDATE returned no rows for activity_id=%s", target_id)
        else:
            logger.warning("coaching_notes NOT saved: no activity found for user=%s today", user_id)

    except Exception as e:
        logger.exception("_send_activity_report error for user=%s: %s", user_id, e)
        await update.message.reply_text(f"⚠️ Report non generato: {e}")


def _get_coaching_comment(result: dict, profile: dict) -> str:
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
