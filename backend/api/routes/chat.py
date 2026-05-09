from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.services.coach_service import get_coach_response_web

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str    # "user" | "assistant"
    content: str


class CoachRequest(BaseModel):
    user_id: str
    message: str
    session_history: list[ChatMessage] = []


@router.post("/coach")
async def coach_chat(body: CoachRequest):
    """Risposta del coach con contesto completo dal DB.

    La session_history è gestita dal frontend e passata ad ogni chiamata.
    """
    if not body.user_id or not body.message.strip():
        raise HTTPException(status_code=400, detail="user_id e message sono obbligatori")

    history = [{"role": m.role, "content": m.content} for m in body.session_history]

    try:
        reply = await get_coach_response_web(body.user_id, body.message, history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"reply": reply}
