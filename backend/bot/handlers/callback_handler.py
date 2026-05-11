from datetime import date, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from backend.database.client import get_supabase
from backend.bot.handlers.command_handler import get_or_create_user

_STATE_TTL_S = 300  # 5 minutes


def _get_meal_interaction(context) -> dict | None:
    if not context:
        return None
    state = context.user_data.get("meal_interaction")
    if not state:
        return None
    if datetime.now().timestamp() - state.get("ts", 0) > _STATE_TTL_S:
        context.user_data.pop("meal_interaction", None)
        return None
    return state


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = await get_or_create_user(update)
    db = get_supabase()
    cb_data = query.data or ""

    if cb_data.startswith("use_food_"):
        await _cb_use_food(query, context, db, user_id, cb_data[len("use_food_"):])
    elif cb_data == "new_food":
        await _cb_new_food(query, context, db, user_id)
    elif cb_data.startswith("save_food_"):
        await _cb_save_food(query, context, db, user_id, cb_data[len("save_food_"):])
    elif cb_data == "skip_food":
        await _cb_skip_food(query, context)
    else:
        await query.edit_message_text("Azione non riconosciuta.")


async def _cb_use_food(query, context, db, user_id: str, food_id: str) -> None:
    from backend.services.food_service import calculate_for_quantity

    state = _get_meal_interaction(context)
    if not state:
        await query.edit_message_text("⏱ Sessione scaduta. Reinserisci il pasto.")
        return

    res = db.table("food_items").select("*").eq("id", food_id).limit(1).execute()
    if not res.data:
        await query.edit_message_text("Alimento non trovato nel database. Reinserisci il pasto.")
        return

    fi = res.data[0]
    qty = float(state.get("item_qty") or 100.0)
    macros = calculate_for_quantity(fi, qty)
    meal_name = state.get("meal_name") or fi["name"]

    db.table("meals").insert({
        "user_id":    user_id,
        "meal_date":  date.today().isoformat(),
        "meal_time":  state.get("meal_time", "snack"),
        "name":       meal_name,
        "calories":   macros["calories"],
        "protein_g":  macros["protein_g"],
        "carbs_g":    macros["carbs_g"],
        "fat_g":      macros["fat_g"],
        "fiber_g":    macros["fiber_g"],
        "quantity_g": qty if qty > 0 else None,
        "source":     state.get("source", "telegram_text"),
    }).execute()

    context.user_data.pop("meal_interaction", None)

    fi_display = fi["name"] + (f" ({fi['brand']})" if fi.get("brand") else "")
    await query.edit_message_text(
        f"✅ *{meal_name}* — {round(macros['calories'])} kcal ({round(qty)}g)\n"
        f"_Dati da: {fi_display}_",
        parse_mode="Markdown",
    )


async def _cb_new_food(query, context, db, user_id: str) -> None:
    state = _get_meal_interaction(context)
    if not state:
        await query.edit_message_text("⏱ Sessione scaduta. Reinserisci il pasto.")
        return

    claude_totals = state.get("claude_totals", {})
    meal_name = state.get("meal_name", "Pasto")
    item_qty  = float(state.get("item_qty") or 100.0)
    meal_time = state.get("meal_time", "snack")
    source    = state.get("source", "telegram_text")

    meal_res = db.table("meals").insert({
        "user_id":    user_id,
        "meal_date":  date.today().isoformat(),
        "meal_time":  meal_time,
        "name":       meal_name,
        "calories":   claude_totals.get("calories", 0),
        "protein_g":  claude_totals.get("protein_g", 0),
        "carbs_g":    claude_totals.get("carbs_g", 0),
        "fat_g":      claude_totals.get("fat_g", 0),
        "fiber_g":    claude_totals.get("fiber_g", 0),
        "quantity_g": item_qty if item_qty > 0 else None,
        "source":     source,
    }).execute()
    meal_id = meal_res.data[0]["id"] if meal_res.data else "none"

    context.user_data["meal_interaction"] = {
        "type":       "save_or_skip",
        "ts":         datetime.now().timestamp(),
        "meal_id":    meal_id,
        "meal_name":  meal_name,
        "item_name":  state.get("item_name"),
        "item_brand": state.get("item_brand"),
        "item_qty":   item_qty,
        "macros":     claude_totals,
        "source":     source,
    }

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ Salva preferito", callback_data=f"save_food_{meal_id}"),
        InlineKeyboardButton("❌ No grazie",        callback_data="skip_food"),
    ]])
    cal = round(claude_totals.get("calories", 0))
    await query.edit_message_text(
        f"✅ *{meal_name}* ({cal} kcal) aggiunto\n"
        f"Vuoi salvarlo negli *Alimenti Preferiti* per riusarlo?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _cb_save_food(query, context, db, user_id: str, meal_id: str) -> None:
    from backend.services.food_service import upsert_food_item

    state = _get_meal_interaction(context)
    if not state:
        await query.edit_message_text(
            "⏱ Sessione scaduta. L'alimento non è stato salvato nei preferiti."
        )
        return

    name   = state.get("item_name") or state.get("meal_name", "Alimento")
    brand  = state.get("item_brand") or None
    source = state.get("source", "telegram_text")

    # Use per_100g values directly if available (e.g. from label photo)
    per_100g = state.get("per_100g")
    if per_100g and per_100g.get("calories"):
        upsert_food_item(
            db, user_id, name, source,
            calories_per_100g=per_100g.get("calories"),
            protein_per_100g=per_100g.get("protein_g"),
            carbs_per_100g=per_100g.get("carbs_g"),
            fat_per_100g=per_100g.get("fat_g"),
            fiber_per_100g=per_100g.get("fiber_g"),
            brand=brand,
        )
    else:
        # Scale macros back to per-100g
        macros = state.get("macros") or {}
        qty = float(state.get("item_qty") or 100.0)
        factor = 100.0 / qty if qty else 1.0
        upsert_food_item(
            db, user_id, name, source,
            calories_per_100g=round((macros.get("calories",  0) or 0) * factor, 1),
            protein_per_100g =round((macros.get("protein_g", 0) or 0) * factor, 1),
            carbs_per_100g   =round((macros.get("carbs_g",   0) or 0) * factor, 1),
            fat_per_100g     =round((macros.get("fat_g",     0) or 0) * factor, 1),
            fiber_per_100g   =round((macros.get("fiber_g",   0) or 0) * factor, 1),
            brand=brand,
        )

    context.user_data.pop("meal_interaction", None)
    await query.edit_message_text(
        f"⭐ *{name}* salvato negli Alimenti Preferiti!",
        parse_mode="Markdown",
    )


async def _cb_skip_food(query, context) -> None:
    context.user_data.pop("meal_interaction", None)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
