from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from backend.config import get_settings
from backend.bot.handlers.command_handler import (
    cmd_start,
    cmd_status,
    cmd_summary,
    cmd_weight,
    cmd_steps,
    cmd_sleep,
    cmd_plan,
    cmd_new_plan,
    cmd_strava,
    cmd_sync_strava,
    cmd_help,
    cmd_alimenti,
)
from backend.bot.handlers.text_handler import handle_text
from backend.bot.handlers.photo_handler import handle_photo
from backend.bot.handlers.voice_handler import handle_voice
from backend.bot.handlers.callback_handler import handle_callback

settings = get_settings()


def build_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("riepilogo", cmd_summary))
    app.add_handler(CommandHandler("peso", cmd_weight))
    app.add_handler(CommandHandler("passi", cmd_steps))
    app.add_handler(CommandHandler("sonno", cmd_sleep))
    app.add_handler(CommandHandler("piano", cmd_plan))
    app.add_handler(CommandHandler("nuovopiano", cmd_new_plan))
    app.add_handler(CommandHandler("strava", cmd_strava))
    app.add_handler(CommandHandler("syncstrava", cmd_sync_strava))
    app.add_handler(CommandHandler("aiuto", cmd_help))
    app.add_handler(CommandHandler("alimenti", cmd_alimenti))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app
