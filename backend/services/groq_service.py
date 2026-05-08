import io
from groq import Groq
from backend.config import get_settings

settings = get_settings()
client = Groq(api_key=settings.groq_api_key)


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Trascrive un file audio usando Groq Whisper."""
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename

    transcription = client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model="whisper-large-v3",
        language="it",
        response_format="text",
    )
    return transcription.strip()
