from telegram import Update
from telegram.ext import ContextTypes
from backend.services.groq_service import transcribe_audio
from backend.bot.handlers.command_handler import get_or_create_user
from backend.bot.handlers.text_handler import dispatch_message


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await get_or_create_user(update)

    await update.message.reply_text("🎙 Sto ascoltando e trascrivendo...")

    try:
        voice = update.message.voice
        voice_file = await voice.get_file()
        audio_bytes = bytes(await voice_file.download_as_bytearray())

        transcript = transcribe_audio(audio_bytes, "audio.ogg")
        await update.message.reply_text(f"📝 Trascritto: _{transcript}_", parse_mode="Markdown")

        await dispatch_message(update, context, user_id, transcript, source="telegram_voice")

    except Exception as e:
        await update.message.reply_text(f"Errore nella trascrizione o analisi: {e}")
