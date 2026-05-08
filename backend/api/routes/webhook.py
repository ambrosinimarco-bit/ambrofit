from fastapi import APIRouter, Request
from telegram import Update
from backend.config import get_settings

router = APIRouter(tags=["webhook"])
settings = get_settings()

_application = None


def set_application(app):
    global _application
    _application = app


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if _application is None:
        return {"ok": False, "error": "Bot not initialized"}
    data = await request.json()
    update = Update.de_json(data, _application.bot)
    await _application.process_update(update)
    return {"ok": True}
