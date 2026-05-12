import asyncio
import io
import re
from datetime import date, datetime, datetime as _dt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from backend.services.claude_service import analyze_food_text, analyze_voice_transcript
from backend.database.client import get_supabase
from backend.bot.handlers.command_handler import get_or_create_user


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)
    text = update.message.text.strip()
    _pending_keys = ("pending_delete_meal", "pending_delete_food")
    if not any(context.user_data.get(k) for k in _pending_keys):
        await update.message.reply_text("Sto analizzando il messaggio...")
    await dispatch_message(update, context, user_id, text, source="telegram_text")


_STATUS_HINTS = ('come sto', 'quanto posso', 'cosa posso mangiare', 'situazione oggi', 'riepilogo')
_PLAN_PATTERNS = ('crea piano', 'pianifica', 'piano settimana', 'piano allenament', 'programma settimana', 'programma allenament')
_LIST_FOOD_PATTERNS = ('mostra alimenti', 'lista alimenti', 'alimenti salvati', 'miei alimenti', 'elenco alimenti', 'elenca alimenti')
_DELETE_MEAL_PATTERNS = ("cancella l'ultimo pasto", "elimina l'ultimo pasto", "togli l'ultimo pasto",
                         "cancella l'ultimo", "elimina l'ultimo", "togli l'ultimo",
                         "cancella il pasto", "elimina il pasto", "togli il pasto", "rimuovi il pasto")

_MEAL_TIME_KEYWORDS = {
    "breakfast": ("colazione", "breakfast", "stamattina", "mattino", "mattina"),
    "lunch":     ("pranzo", "lunch", "mezzogiorno", "a pranzo", "per pranzo"),
    "dinner":    ("cena", "dinner", "stasera", "sera", "a cena", "per cena"),
}

def _extract_meal_time(text: str) -> str | None:
    """Returns the meal type if the text contains an explicit indication, else None."""
    t = text.lower()
    for meal_time, keywords in _MEAL_TIME_KEYWORDS.items():
        if any(k in t for k in keywords):
            return meal_time
    return None

_STRONG_INTERROGATIVES = (
    'quale ', 'quali ', 'perché ', 'perche ', 'chi ', 'dove ',
    'spiegami ', 'parlami ', 'descrivimi ', 'che ftp', 'che potenza',
    'che zone', 'che watt', 'quali zone', 'qual è il mio', "qual è la mia",
)


def _quick_classify(text: str) -> str | None:
    """Pre-filtro veloce senza Claude. Ritorna il tipo se il messaggio è inequivocabile, None altrimenti."""
    t = text.strip()
    t_lower = t.lower()

    if '?' in t:
        if any(p in t_lower for p in _STATUS_HINTS):
            return 'status'
        return 'coach'

    if any(t_lower.startswith(s) for s in _STRONG_INTERROGATIVES):
        return 'coach'

    if any(p in t_lower for p in _PLAN_PATTERNS):
        return 'plan_request'

    if any(p in t_lower for p in _LIST_FOOD_PATTERNS):
        return 'list_food_items'

    if any(p in t_lower for p in _DELETE_MEAL_PATTERNS):
        return 'delete_meal'

    return None


_BRUCIATE_RE = re.compile(
    r'(?:calorie\s+)?bruciat[eo]\s+(\d+(?:[.,]\d+)?)'
    r'|(\d+(?:[.,]\d+)?)\s+(?:calorie\s+)?bruciat[eo]',
    re.IGNORECASE,
)


async def dispatch_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str,
    text: str,
    source: str = "telegram_text",
) -> None:
    """Classifica il testo (o trascritto vocale) e smista all'azione corretta."""
    try:
        # ── Handle pending meal deletion confirmation ──────────────────
        pending_dm = context.user_data.get("pending_delete_meal") if context else None
        if pending_dm:
            t_up = text.strip().upper()
            if t_up == "SI":
                db_inner = get_supabase()
                db_inner.table("meals").delete().eq("id", pending_dm["meal_id"]).execute()
                del context.user_data["pending_delete_meal"]
                await update.message.reply_text(
                    f"✅ Pasto eliminato: *{pending_dm['meal_name']}* ({round(pending_dm['calories'])} kcal)",
                    parse_mode="Markdown",
                )
            elif t_up == "ANNULLA":
                del context.user_data["pending_delete_meal"]
                await update.message.reply_text("❌ Eliminazione annullata.")
            else:
                await update.message.reply_text(
                    f"Vuoi eliminare *{pending_dm['meal_name']}*? Rispondi *SI* o *ANNULLA*.",
                    parse_mode="Markdown",
                )
            return

        # ── Handle pending food_item deletion confirmation ─────────────
        pending_df = context.user_data.get("pending_delete_food") if context else None
        if pending_df:
            t_up = text.strip().upper()
            if t_up == "SI":
                db_inner = get_supabase()
                db_inner.table("food_items").delete().eq("id", pending_df["food_id"]).execute()
                del context.user_data["pending_delete_food"]
                await update.message.reply_text(
                    f"✅ Alimento eliminato dal database: *{pending_df['food_name']}*",
                    parse_mode="Markdown",
                )
            elif t_up == "ANNULLA":
                del context.user_data["pending_delete_food"]
                await update.message.reply_text("❌ Eliminazione annullata.")
            else:
                await update.message.reply_text(
                    f"Vuoi eliminare *{pending_df['food_name']}* dal database? Rispondi *SI* o *ANNULLA*.",
                    parse_mode="Markdown",
                )
            return

        # ── Handle "bruciate X" / "calorie bruciate X" ────────────────
        m_bruciate = _BRUCIATE_RE.search(text)
        if m_bruciate:
            raw = (m_bruciate.group(1) or m_bruciate.group(2)).replace(',', '.')
            await _handle_bruciate(update, db := get_supabase(), user_id, int(round(float(raw))))
            return

        quick = _quick_classify(text)
        if quick:
            data_type = quick
            data = {}
        else:
            classification = analyze_voice_transcript(text)
            data_type = classification.get("type", "meal")
            data = classification.get("data", {})
            # Rete di sicurezza: mai classificare come pasto un messaggio che è una domanda
            if data_type == "meal" and '?' in text:
                data_type = "coach"
                data = {}
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
            # Recupera eventuale pre-condizione registrata oggi in daily_health
            today_str = date.today().isoformat()
            pre_cond_res = db.table("daily_health").select("pre_condition,sleep_hours,stress_score")\
                .eq("user_id", user_id).eq("health_date", today_str).limit(1).execute()
            pre_cond_data = (pre_cond_res.data or [{}])[0]

            db.table("activities").insert({
                "user_id": user_id,
                "activity_date": today_str,
                "activity_type": data.get("activity_type", "other"),
                "name": data.get("name", text[:50]),
                "duration_min": data.get("duration_min", 0),
                "distance_km": data.get("distance_km"),
                "notes": text,
                "source": source,
                "condition_pre": pre_cond_data.get("pre_condition") or None,
                "sleep_hours": pre_cond_data.get("sleep_hours") or None,
                "stress_level": pre_cond_data.get("stress_score") or None,
            }).execute()

            activity_msg = (
                f"✅ *Attività registrata:* {data.get('name', 'Attività')}\n"
                f"⏱ `{data.get('duration_min', 0)} min`"
                + (f" · 📍 `{data.get('distance_km')} km`" if data.get("distance_km") else "")
            )
            if pre_cond_data.get("pre_condition"):
                activity_msg += f"\n💭 _Pre-condizione rilevata: {pre_cond_data['pre_condition']}_"

            activity_msg += (
                "\n\n📋 *Check-in post-sessione* — rispondimi liberamente:\n"
                "• Come stavi *PRIMA* di iniziare? _(riposato, stanco, gambe pesanti...)_\n"
                "• Com'è andata *DURANTE*? _(bene, faticoso, dolori...)_\n"
                "• Come ti senti *ORA*? _(soddisfatto, esausto, fastidi fisici...)_\n"
                "• Ore di sonno ieri notte?\n"
                "• Livello stress oggi 1-10?\n"
                "• Voto RPE 1-10 per l'intensità percepita\n\n"
                "_Puoi rispondere in un unico messaggio, es: \"Ero stanco. "
                "Durante è andata bene fino al km 30 poi ho sofferto. "
                "Ora mi sento ok. Dormito 6h, stress 4, RPE 7\"_"
            )
            await update.message.reply_text(activity_msg, parse_mode="Markdown")

        elif data_type == "check_in":
            await _handle_check_in(update, db, user_id, data)

        elif data_type == "pre_condition":
            await _handle_pre_condition(update, db, user_id, data)

        elif data_type == "coach":
            from backend.services.coach_service import get_coach_response
            await update.message.reply_text("🧠 Sto elaborando la risposta del coach...")
            response_text = await get_coach_response(user_id, text)
            await update.message.reply_text(response_text)

        elif data_type == "zwo_request":
            await _handle_zwo_request(update, db, user_id, text)

        elif data_type == "plan_request":
            await _handle_plan_request(update, db, user_id, text)

        elif data_type == "list_food_items":
            await _handle_list_food_items(update, db, user_id)

        elif data_type == "food_lookup":
            await _handle_food_lookup(update, db, user_id, data.get("query") or text)

        elif data_type == "delete_food_item":
            await _handle_delete_food_item(update, context, db, user_id, data.get("query") or text)

        elif data_type == "delete_meal":
            await _handle_delete_meal(update, context, db, user_id, data)

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
            # ── Pasto — inline-button flow ───────────────────────────────
            from backend.services.food_service import extract_quantity_g, lookup_food_item_fuzzy

            result    = analyze_food_text(text)
            meal_time = _extract_meal_time(text) or result.get("meal_time") or "snack"
            items     = result.get("items", [])

            if not items:
                await update.message.reply_text(
                    "Non ho capito cosa hai mangiato. Puoi essere più specifico?"
                )
                return

            if len(items) == 1:
                # ── Single food: fuzzy search → inline buttons ───────────
                item       = items[0]
                item_name  = item.get("name") or ""
                item_brand = item.get("brand") or None
                item_qty   = float(item.get("quantity_g") or 0) or (extract_quantity_g(text) or 100.0)
                meal_name  = item_name
                if item_brand and item_brand.lower() not in item_name.lower():
                    meal_name = f"{item_name} {item_brand}"
                claude_totals = {
                    "calories":  item.get("calories", 0),
                    "protein_g": item.get("protein_g", 0),
                    "carbs_g":   item.get("carbs_g", 0),
                    "fat_g":     item.get("fat_g", 0),
                    "fiber_g":   item.get("fiber_g", 0),
                }
                fi = lookup_food_item_fuzzy(db, user_id, item_name or meal_name) if (item_name or meal_name) else None

                if fi:
                    fi_display = fi["name"] + (f" ({fi['brand']})" if fi.get("brand") else "")
                    if context:
                        context.user_data["meal_interaction"] = {
                            "type": "use_or_new", "ts": datetime.now().timestamp(),
                            "food_found": fi, "meal_name": meal_name,
                            "item_name": item_name, "item_brand": item_brand,
                            "item_qty": item_qty, "meal_time": meal_time,
                            "source": source, "text": text, "claude_totals": claude_totals,
                        }
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Usa questo", callback_data=f"use_food_{fi['id']}"),
                        InlineKeyboardButton("➕ Crea nuovo",  callback_data="new_food"),
                    ]])
                    await update.message.reply_text(
                        f"Ho trovato *{fi_display}* negli Alimenti Preferiti.\n"
                        f"Usare quello o creare nuovo?",
                        parse_mode="Markdown", reply_markup=keyboard,
                    )
                else:
                    meal_res = db.table("meals").insert({
                        "user_id":   user_id, "meal_date": date.today().isoformat(),
                        "meal_time": meal_time, "name": meal_name,
                        "calories":  claude_totals["calories"],
                        "protein_g": claude_totals["protein_g"],
                        "carbs_g":   claude_totals["carbs_g"],
                        "fat_g":     claude_totals["fat_g"],
                        "fiber_g":   claude_totals["fiber_g"],
                        "quantity_g": item_qty if item_qty > 0 else None,
                        "notes": text, "source": source,
                    }).execute()
                    meal_id = meal_res.data[0]["id"] if meal_res.data else "none"
                    if context:
                        context.user_data["meal_interaction"] = {
                            "type": "save_or_skip", "ts": datetime.now().timestamp(),
                            "meal_id": meal_id, "meal_name": meal_name,
                            "item_name": item_name, "item_brand": item_brand,
                            "item_qty": item_qty, "macros": claude_totals, "source": source,
                        }
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("⭐ Salva preferito", callback_data=f"save_food_{meal_id}"),
                        InlineKeyboardButton("❌ No grazie", callback_data="skip_food"),
                    ]])
                    cal = round(claude_totals.get("calories", 0))
                    await update.message.reply_text(
                        f"✅ *{meal_name}* ({cal} kcal) aggiunto\n"
                        f"Vuoi salvarlo negli *Alimenti Preferiti* per riusarlo?",
                        parse_mode="Markdown", reply_markup=keyboard,
                    )
            else:
                # ── Multi-item meal: save immediately, no buttons ────────
                total_cal   = result.get("total_calories", 0)
                total_prot  = result.get("total_protein_g", 0)
                total_carbs = result.get("total_carbs_g", 0)
                total_fat   = result.get("total_fat_g", 0)
                total_fiber = result.get("total_fiber_g", 0)
                meal_name   = result.get("meal_name") or text[:50]
                db.table("meals").insert({
                    "user_id":   user_id, "meal_date": date.today().isoformat(),
                    "meal_time": meal_time, "name": meal_name,
                    "calories":  total_cal, "protein_g": total_prot,
                    "carbs_g":   total_carbs, "fat_g": total_fat, "fiber_g": total_fiber,
                    "notes": text, "source": source,
                }).execute()
                conf = {"high": "✅", "medium": "⚠️", "low": "❓"}.get(result.get("confidence", "medium"), "⚠️")
                items_lines = "\n".join(
                    f"  • {i.get('name','')}{' (' + i['brand'] + ')' if i.get('brand') else ''}: {i.get('calories',0)} kcal"
                    for i in items
                )
                await update.message.reply_text(
                    f"{conf} *{meal_name}*\n\n{items_lines}\n\n🔥 Totale: `{round(total_cal)} kcal`",
                    parse_mode="Markdown",
                )

    except Exception as e:
        await update.message.reply_text(
            f"Non ho capito il messaggio. Prova a essere più specifico.\nErrore: {e}"
        )


async def _handle_check_in(update, db, user_id: str, data: dict) -> None:
    """Aggiorna l'ultima attività del giorno con tutti i dati di percezione."""
    today = date.today().isoformat()

    # Trova l'ultima attività del giorno senza check-in
    result = db.table("activities").select("*").eq("user_id", user_id)\
        .eq("activity_date", today).eq("check_in_done", False)\
        .order("created_at", desc=True).limit(1).execute()
    if not result.data:
        result = db.table("activities").select("*").eq("user_id", user_id)\
            .eq("activity_date", today).order("created_at", desc=True).limit(1).execute()
    if not result.data:
        await update.message.reply_text(
            "Non trovo attività registrate oggi da aggiornare. Registra prima un'attività!"
        )
        return

    activity = result.data[0]
    update_data = {"check_in_done": True}

    rpe             = data.get("rpe")
    physical_notes  = data.get("physical_notes") or ""
    condition_pre   = data.get("condition_pre") or ""
    condition_during= data.get("condition_during") or ""
    condition_post  = data.get("condition_post") or ""
    sleep_hours     = data.get("sleep_hours")
    stress_level    = data.get("stress_level")

    if rpe is not None:         update_data["rpe"] = int(rpe)
    if physical_notes:          update_data["physical_notes"] = physical_notes
    if condition_pre:           update_data["condition_pre"] = condition_pre
    if condition_during:        update_data["condition_during"] = condition_during
    if condition_post:          update_data["condition_post"] = condition_post
    if sleep_hours is not None: update_data["sleep_hours"] = float(sleep_hours)
    if stress_level is not None:update_data["stress_level"] = int(stress_level)

    db.table("activities").update(update_data).eq("id", activity["id"]).execute()

    # Aggiorna anche daily_health con sleep/stress se forniti
    if sleep_hours is not None or stress_level is not None:
        health_update = {}
        if sleep_hours is not None:  health_update["sleep_hours"] = float(sleep_hours)
        if stress_level is not None: health_update["stress_score"] = int(stress_level)
        _upsert_health(db, user_id, health_update)

    # Risposta coaching
    rpe_int = int(rpe) if rpe is not None else None
    if rpe_int is not None:
        if rpe_int <= 5:
            coaching_comment = "Sessione facile — buon recupero attivo."
        elif rpe_int <= 7:
            coaching_comment = "Range ideale per l'allenamento base, ottima gestione."
        elif rpe_int <= 8:
            coaching_comment = "Buona intensità — monitora come recuperi nelle 24h."
        else:
            coaching_comment = "Sessione molto impegnativa — priorità assoluta al recupero nelle prossime 48h."
    else:
        coaching_comment = ""

    reply = f"✅ *Check-in registrato per:* {activity.get('name', 'Attività')}\n"
    if condition_pre:    reply += f"😴 Prima: _{condition_pre}_\n"
    if condition_during: reply += f"🚴 Durante: _{condition_during}_\n"
    if condition_post:   reply += f"🏁 Dopo: _{condition_post}_\n"
    if sleep_hours:      reply += f"💤 Sonno: `{sleep_hours}h`\n"
    if stress_level:     reply += f"😤 Stress: `{stress_level}/10`\n"
    if rpe_int:          reply += f"📊 RPE: `{rpe_int}/10`\n"
    if physical_notes:   reply += f"⚠ Fisico: _{physical_notes}_\n"
    if coaching_comment: reply += f"\n🎯 {coaching_comment}"

    await update.message.reply_text(reply, parse_mode="Markdown")


async def _handle_pre_condition(update, db, user_id: str, data: dict) -> None:
    """Salva la condizione pre-allenamento nel profilo giornaliero."""
    condition_pre = data.get("condition_pre") or ""
    sleep_hours   = data.get("sleep_hours")
    stress_level  = data.get("stress_level")

    health_update = {}
    if condition_pre:            health_update["pre_condition"] = condition_pre
    if sleep_hours is not None:  health_update["sleep_hours"] = float(sleep_hours)
    if stress_level is not None: health_update["stress_score"] = int(stress_level)

    if not health_update:
        await update.message.reply_text("Non ho capito. Dimmi come ti senti o quante ore hai dormito.")
        return

    _upsert_health(db, user_id, health_update)

    parts = []
    if condition_pre: parts.append(f"condizione: _{condition_pre}_")
    if sleep_hours:   parts.append(f"sonno: `{sleep_hours}h`")
    if stress_level:  parts.append(f"stress: `{stress_level}/10`")

    reply = "💭 *Pre-condizione registrata:* " + " | ".join(parts)
    reply += "\n\n_La terrò in conto quando registrerai l'attività di oggi._"
    await update.message.reply_text(reply, parse_mode="Markdown")


async def _handle_zwo_request(update, db, user_id: str, text: str) -> None:
    """Genera e invia un file .zwo via Telegram."""
    from backend.services.claude_service import plan_zwo_workout
    from backend.services.zwo_service import generate_zwo_xml, safe_filename

    # Fetch profilo utente
    profile_res = db.table("user_profiles").select("ftp_watts,weight_kg").eq("id", user_id).limit(1).execute()
    profile = (profile_res.data or [{}])[0]
    ftp = profile.get("ftp_watts") or 200
    weight_kg = profile.get("weight_kg") or 75.0

    await update.message.reply_text("⚙️ Sto pianificando il workout con Claude AI...")

    workout = await asyncio.to_thread(plan_zwo_workout, text, ftp)
    xml_content = generate_zwo_xml(workout, ftp, weight_kg)

    # Nome file sicuro
    workout_name = workout.get("name", "Workout")
    safe_name = safe_filename(workout_name)

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


async def _handle_plan_request(update, db, user_id: str, text: str) -> None:
    """Genera un piano settimanale e invia il riepilogo testuale via Telegram."""
    import asyncio
    from backend.services.plan_generator_service import generate_weekly_plan

    t = text.lower()
    if "recupero" in t:
        objective = "recupero"
    elif any(w in t for w in ("qualità", "qualita", "sweet spot", "intervalli", "soglia")):
        objective = "qualità"
    elif any(w in t for w in ("gara", "pre-gara", "evento")):
        objective = "pre-gara"
    else:
        objective = "base aerobica"

    period = "next_week" if any(w in t for w in ("prossim", "prossima")) else "current_week"

    await update.message.reply_text("🗓️ Sto generando il piano settimanale con Claude AI...")

    try:
        plan = await asyncio.to_thread(generate_weekly_plan, user_id, period, objective)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Errore nella generazione del piano: {e}")
        return

    sessions = plan.get("sessions", [])
    summary = plan.get("summary", "")
    metrics = plan.get("metrics", {})
    period_info = plan.get("period", {})

    _ICONS = {"recovery": "🟢", "base": "🔵", "long": "🔵", "sweetspot": "🟡",
              "tempo": "🟠", "vo2max": "🔴", "strength": "🏋️", "mobility": "🧘", "rest": "⬜"}

    lines = []
    for s in sessions:
        stype = s.get("type", "base")
        if stype == "rest":
            lines.append(f"⬜ *{s.get('day_name','').capitalize()}*: riposo")
            continue
        icon = _ICONS.get(stype, "🔵")
        name = s.get("name") or stype
        dur = s.get("duration_min") or 0
        indoor = " 🏠" if s.get("indoor") else ""
        short_desc = (s.get("description") or "")[:70]
        lines.append(
            f"{icon} *{s.get('day_name','').capitalize()}*{indoor}: {name} `{dur}'`\n"
            f"  _{short_desc}_"
        )

    reply = (
        f"🗓️ *Piano {objective}*\n"
        f"_{period_info.get('start')} → {period_info.get('end')}_\n"
        f"CTL `{metrics.get('ctl')}` | ATL `{metrics.get('atl')}` | TSB `{metrics.get('tsb')}`\n\n"
        + "\n".join(lines)
        + f"\n\n_{summary}_"
        + "\n\n📥 Apri la dashboard → sezione *Piano* per scaricare il calendario ICS e i file .zwo"
    )
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


# ── Food management helpers ───────────────────────────────────────────────────

async def _handle_list_food_items(update, db, user_id: str) -> None:
    items = db.table("food_items").select("*").eq("user_id", user_id)\
        .order("name").limit(10).execute().data or []
    if not items:
        await update.message.reply_text(
            "Nessun alimento negli Alimenti Preferiti.\n"
            "Quando inserisci un pasto, premi ⭐ per salvarlo nei preferiti."
        )
        return
    total_res = db.table("food_items").select("id").eq("user_id", user_id).execute()
    total = len(total_res.data or [])
    lines = []
    for f in items:
        brand = f" ({f['brand']})" if f.get("brand") else ""
        cal  = round(f.get("calories_per_100g") or 0)
        prot = f.get("protein_per_100g") or 0
        carbs = f.get("carbs_per_100g") or 0
        fat  = f.get("fat_per_100g") or 0
        lines.append(f"• *{f['name']}*{brand}\n  {cal} kcal · P:{prot}g · C:{carbs}g · G:{fat}g /100g")
    suffix = f"\n\n_Mostrati 10 di {total}. Usa la dashboard per vedere tutti._" if total > 10 else ""
    await update.message.reply_text(
        f"⭐ *Alimenti Preferiti* ({total} totali):\n\n" + "\n\n".join(lines) + suffix,
        parse_mode="Markdown",
    )


async def _handle_food_lookup(update, db, user_id: str, query: str) -> None:
    from backend.services.food_service import lookup_food_item_fuzzy, clean_food_name
    clean_q = clean_food_name(query) or query.strip()
    fi = lookup_food_item_fuzzy(db, user_id, clean_q)
    if not fi:
        await update.message.reply_text(
            f"🔍 Non ho trovato *{clean_q}* nel tuo database personale.\n"
            "Puoi aggiungerlo mandando una foto dell'etichetta o inserendo un pasto con quel nome.",
            parse_mode="Markdown",
        )
        return
    brand = f" ({fi['brand']})" if fi.get("brand") else ""
    cal   = round(fi.get("calories_per_100g") or 0)
    prot  = fi.get("protein_per_100g") or 0
    carbs = fi.get("carbs_per_100g") or 0
    fat   = fi.get("fat_per_100g") or 0
    fib   = fi.get("fiber_per_100g") or 0
    src   = fi.get("source", "")
    source_note = f"\n_Fonte: {src}_" if src else ""
    await update.message.reply_text(
        f"📦 *{fi['name']}*{brand}\n\n"
        f"Per 100g:\n"
        f"🔥 Calorie: `{cal} kcal`\n"
        f"💪 Proteine: `{prot}g`\n"
        f"🌾 Carboidrati: `{carbs}g`\n"
        f"🫒 Grassi: `{fat}g`\n"
        f"🌿 Fibre: `{fib}g`"
        f"{source_note}",
        parse_mode="Markdown",
    )


async def _handle_delete_food_item(update, context, db, user_id: str, query: str) -> None:
    from backend.services.food_service import lookup_food_item_fuzzy, clean_food_name
    clean_q = clean_food_name(query) or query.strip()
    fi = lookup_food_item_fuzzy(db, user_id, clean_q)
    if not fi:
        await update.message.reply_text(
            f"🔍 Non ho trovato *{clean_q}* nel database personale.",
            parse_mode="Markdown",
        )
        return
    if context:
        context.user_data.pop("pending_meal", None)
        context.user_data.pop("pending_delete_meal", None)
        context.user_data["pending_delete_food"] = {
            "food_id":   fi["id"],
            "food_name": fi["name"],
        }
    await update.message.reply_text(
        f"Vuoi eliminare *{fi['name']}* dal database personale?\n"
        f"Rispondi *SI* per confermare o *ANNULLA* per annullare.",
        parse_mode="Markdown",
    )


async def _handle_delete_meal(update, context, db, user_id: str, data: dict) -> None:
    today = date.today().isoformat()
    target = data.get("target", "last")
    query  = data.get("query", "")

    if target == "name" and query:
        from backend.services.food_service import clean_food_name
        clean_q = clean_food_name(query) or query.strip()
        meals = db.table("meals").select("*").eq("user_id", user_id)\
            .eq("meal_date", today).ilike("name", f"%{clean_q}%")\
            .order("created_at", desc=True).limit(1).execute().data or []
    else:
        meals = db.table("meals").select("*").eq("user_id", user_id)\
            .eq("meal_date", today).order("created_at", desc=True).limit(1).execute().data or []

    if not meals:
        await update.message.reply_text("Non ho trovato pasti registrati oggi da eliminare.")
        return

    meal = meals[0]
    if context:
        context.user_data.pop("pending_meal", None)
        context.user_data.pop("pending_delete_food", None)
        context.user_data["pending_delete_meal"] = {
            "meal_id":   meal["id"],
            "meal_name": meal["name"],
            "calories":  meal.get("calories", 0),
        }
    cal_str = f" ({round(meal.get('calories', 0))} kcal)" if meal.get("calories") else ""
    await update.message.reply_text(
        f"Vuoi eliminare *{meal['name']}*{cal_str}?\n"
        f"Rispondi *SI* per confermare o *ANNULLA* per annullare.",
        parse_mode="Markdown",
    )


async def _handle_bruciate(update, db, user_id: str, calories: int) -> None:
    """Salva active_calories_manual e risponde con il riepilogo calorico."""
    today = date.today().isoformat()
    existing = db.table("daily_health").select("id")\
        .eq("user_id", user_id).eq("health_date", today).limit(1).execute()
    row = {"user_id": user_id, "health_date": today, "active_calories_manual": calories}
    if existing.data:
        db.table("daily_health").update({"active_calories_manual": calories})\
            .eq("id", existing.data[0]["id"]).execute()
    else:
        db.table("daily_health").insert(row).execute()

    # Calcola stima EOD
    now = _dt.now()
    elapsed = now.hour + now.minute / 60
    eod = max(1900, round(calories / elapsed * 24)) if elapsed >= 1 else 1900

    # Riepilogo calorie assunte oggi
    meals_res = db.table("meals").select("calories").eq("user_id", user_id).eq("meal_date", today).execute()
    calories_in = round(sum(m.get("calories", 0) for m in (meals_res.data or [])))
    bilancio = calories_in - eod
    bal_emoji = "🟢" if bilancio <= 0 else "🔴"

    await update.message.reply_text(
        f"🔥 *Calorie bruciate attuali* registrate: `{calories} kcal`\n\n"
        f"📈 *Stima a fine giornata:* `{eod} kcal`\n"
        f"  _(proiezione alle ore {now.strftime('%H:%M')})_\n\n"
        f"🍽 *Assunte oggi:* `{calories_in} kcal`\n"
        f"⚖️ *Bilancio stimato:* `{bilancio:+d} kcal` {bal_emoji}",
        parse_mode="Markdown",
    )
