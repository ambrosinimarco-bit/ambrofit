import httpx
from datetime import datetime, timezone
from backend.config import get_settings
from backend.database.client import get_supabase

settings = get_settings()

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

SPORT_TYPE_MAP = {
    "Run": "run",
    "TrailRun": "run",
    "Ride": "ride",
    "MountainBikeRide": "ride",
    "GravelRide": "ride",
    "VirtualRide": "ride",
    "Swim": "swim",
    "Walk": "walk",
    "Hike": "hike",
    "WeightTraining": "strength",
    "Yoga": "yoga",
}


def get_auth_url(state: str = "") -> str:
    params = (
        f"client_id={settings.strava_client_id}"
        f"&redirect_uri={settings.strava_redirect_uri}"
        f"&response_type=code"
        f"&scope=activity:read_all"
        f"&state={state}"
    )
    return f"{STRAVA_AUTH_URL}?{params}"


async def exchange_code_for_token(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        resp.raise_for_status()
        return resp.json()


async def get_valid_token(user_id: str) -> str | None:
    db = get_supabase()
    result = db.table("user_profiles").select("*").eq("id", user_id).single().execute()
    if not result.data:
        return None

    user = result.data
    expires_at = user.get("strava_token_expires_at")
    if not expires_at:
        return None

    expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    if now >= expires_dt:
        token_data = await refresh_access_token(user["strava_refresh_token"])
        db.table("user_profiles").update({
            "strava_access_token": token_data["access_token"],
            "strava_refresh_token": token_data["refresh_token"],
            "strava_token_expires_at": datetime.fromtimestamp(
                token_data["expires_at"], tz=timezone.utc
            ).isoformat(),
        }).eq("id", user_id).execute()
        return token_data["access_token"]

    return user["strava_access_token"]


def _map_activity(act: dict, user_id: str) -> dict:
    sport = act.get("sport_type", act.get("type", "other"))
    activity_type = SPORT_TYPE_MAP.get(sport, "other")
    start_dt = datetime.fromisoformat(act["start_date_local"].replace("Z", ""))

    def _to_int(val):
        return int(round(val)) if val is not None else None

    def _to_float(val):
        return round(float(val), 1) if val is not None else None

    # average_watts and average_cadence are present in SummaryActivity (list endpoint).
    # weighted_average_watts (NP) is only in DetailedActivity — pre-fetched when device_watts=True.
    avg_power      = _to_int(act.get("average_watts"))
    np_power       = _to_int(act.get("weighted_average_watts"))
    avg_cadence    = _to_float(act.get("average_cadence"))

    return {
        "user_id": user_id,
        "activity_date": start_dt.date().isoformat(),
        "activity_type": activity_type,
        "name": act.get("name", "Attività Strava"),
        "duration_min": round(act.get("moving_time", 0) / 60, 1),
        "distance_km": round(act.get("distance", 0) / 1000, 2) if act.get("distance") else None,
        "elevation_m": act.get("total_elevation_gain"),
        "calories": act.get("calories") or None,
        "avg_heart_rate": _to_int(act.get("average_heartrate")),
        "max_heart_rate": _to_int(act.get("max_heartrate")),
        "avg_power_w": avg_power,
        "normalized_power_w": np_power,
        "avg_cadence_rpm": avg_cadence,
        "strava_id": str(act["id"]),
        "source": "strava",
    }


async def sync_recent_activities(user_id: str, days: int = 30) -> list[dict]:
    """Sincronizza le attività recenti da Strava.

    Per le ride con power meter (device_watts=True) esegue una seconda
    chiamata al detail endpoint per recuperare weighted_average_watts (NP),
    che non è disponibile nell'endpoint lista.
    """
    token = await get_valid_token(user_id)
    if not token:
        return []

    db = get_supabase()
    after_ts = int((datetime.now(timezone.utc).timestamp()) - days * 86400)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers=headers,
            params={"after": after_ts, "per_page": 100},
        )
        resp.raise_for_status()
        activities = resp.json()

        # Fetch detail endpoint for power-meter rides to get NP (weighted_average_watts).
        # average_watts and average_cadence are already in the list response.
        for act in activities:
            sport = act.get("sport_type", act.get("type", ""))
            is_power_ride = (
                act.get("device_watts")
                and SPORT_TYPE_MAP.get(sport, "other") == "ride"
            )
            if is_power_ride:
                try:
                    det = await client.get(
                        f"{STRAVA_API_BASE}/activities/{act['id']}",
                        headers=headers,
                    )
                    if det.status_code == 200:
                        act["weighted_average_watts"] = det.json().get("weighted_average_watts")
                except Exception:
                    pass

    imported = []
    for act in activities:
        try:
            mapped = _map_activity(act, user_id)
            existing = db.table("activities").select("id").eq("strava_id", str(act["id"])).execute()
            if not existing.data:
                result = db.table("activities").insert(mapped).execute()
                if result.data:
                    imported.append(result.data[0])
        except Exception:
            continue

    return imported


async def import_single_activity(user_id: str, strava_activity_id: int) -> dict | None:
    """Importa una singola attività Strava (usata dal webhook)."""
    token = await get_valid_token(user_id)
    if not token:
        return None

    db = get_supabase()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/activities/{strava_activity_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        act = resp.json()

    mapped = _map_activity(act, user_id)
    existing = db.table("activities").select("id").eq("strava_id", str(strava_activity_id)).execute()
    if existing.data:
        result = db.table("activities").update(mapped).eq("strava_id", str(strava_activity_id)).execute()
    else:
        result = db.table("activities").insert(mapped).execute()

    return result.data[0] if result.data else None


async def register_webhook() -> dict:
    """Registra il webhook Strava (eseguire una volta)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.strava.com/api/v3/push_subscriptions",
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "callback_url": f"{settings.app_base_url}/api/strava/webhook",
                "verify_token": settings.strava_webhook_verify_token,
            },
        )
        return resp.json()
