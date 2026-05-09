from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.services.coach_service import get_coach_response_web
from backend.database.client import get_supabase

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str    # "user" | "assistant"
    content: str


class CoachRequest(BaseModel):
    user_id: str
    message: str
    session_history: list[ChatMessage] = []
    session_id: str | None = None


@router.post("/coach")
async def coach_chat(body: CoachRequest):
    if not body.user_id or not body.message.strip():
        raise HTTPException(status_code=400, detail="user_id e message sono obbligatori")

    history = [{"role": m.role, "content": m.content} for m in body.session_history]

    try:
        reply, session_id = await get_coach_response_web(
            body.user_id, body.message, history, body.session_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"reply": reply, "session_id": session_id}


@router.get("/history/{user_id}")
def get_chat_history(user_id: str, days: int = 7):
    """Ritorna le conversazioni raggruppate per sessione, ordinate per data decrescente."""
    db = get_supabase()
    since = (date.today() - timedelta(days=days)).isoformat()

    result = db.table("coach_conversations")\
        .select("id,role,message,session_id,created_at")\
        .eq("user_id", user_id)\
        .gte("created_at", since)\
        .order("created_at")\
        .execute()

    rows = result.data or []

    sessions: dict[str, dict] = {}
    for row in rows:
        sid = row["session_id"]
        if sid not in sessions:
            sessions[sid] = {
                "session_id": sid,
                "date": (row.get("created_at") or "")[:10],
                "messages": [],
            }
        sessions[sid]["messages"].append({
            "role": row["role"],
            "content": row["message"],
            "created_at": row.get("created_at") or "",
        })

    return sorted(sessions.values(), key=lambda s: s["date"], reverse=True)
