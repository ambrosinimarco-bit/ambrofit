from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from backend.services import strava_service
from backend.database.client import get_supabase
from backend.config import get_settings
from datetime import datetime, timezone

router = APIRouter(prefix="/api/strava", tags=["strava"])
settings = get_settings()


@router.get("/connect/{user_id}")
def strava_connect(user_id: str):
    url = strava_service.get_auth_url(state=user_id)
    return RedirectResponse(url)


@router.get("/callback")
async def strava_callback(code: str, state: str, background_tasks: BackgroundTasks):
    try:
        token_data = await strava_service.exchange_code_for_token(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore OAuth Strava: {e}")

    db = get_supabase()
    athlete = token_data.get("athlete", {})

    db.table("user_profiles").update({
        "strava_athlete_id": str(athlete.get("id", "")),
        "strava_access_token": token_data["access_token"],
        "strava_refresh_token": token_data["refresh_token"],
        "strava_token_expires_at": datetime.fromtimestamp(
            token_data["expires_at"], tz=timezone.utc
        ).isoformat(),
    }).eq("id", state).execute()

    background_tasks.add_task(strava_service.sync_recent_activities, state, 30)

    return HTMLResponse("""
    <html><body style="font-family:sans-serif;text-align:center;padding:50px">
    <h2>✅ Strava collegato!</h2>
    <p>Le attività vengono sincronizzate in background.</p>
    <p>Puoi chiudere questa finestra.</p>
    </body></html>
    """)


@router.get("/webhook")
async def strava_webhook_verify(request: Request):
    """Verifica subscription webhook Strava."""
    params = dict(request.query_params)
    if params.get("hub.verify_token") == settings.strava_webhook_verify_token:
        return {"hub.challenge": params.get("hub.challenge")}
    raise HTTPException(status_code=403, detail="Invalid verify token")


@router.post("/webhook")
async def strava_webhook_event(request: Request, background_tasks: BackgroundTasks):
    """Riceve eventi webhook Strava."""
    body = await request.json()
    object_type = body.get("object_type")
    aspect_type = body.get("aspect_type")
    object_id = body.get("object_id")
    owner_id = str(body.get("owner_id", ""))

    if object_type == "activity" and aspect_type in ("create", "update"):
        db = get_supabase()
        user = db.table("user_profiles").select("id").eq("strava_athlete_id", owner_id).execute()
        if user.data:
            user_id = user.data[0]["id"]
            background_tasks.add_task(strava_service.import_single_activity, user_id, object_id)

    return {"ok": True}


@router.post("/sync/{user_id}")
async def manual_sync(user_id: str, days: int = 30):
    imported = await strava_service.sync_recent_activities(user_id, days)
    return {"imported": len(imported), "activities": imported}


@router.post("/register-webhook")
async def register_webhook():
    result = await strava_service.register_webhook()
    return result
