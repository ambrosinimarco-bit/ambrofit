import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from backend.config import get_settings
from backend.api.routes import meals, activities, health, strava, dashboard, training, webhook
from backend.api.routes.exercises import router as exercises_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.bot.telegram_bot import build_application
    from backend.api.routes.webhook import set_application

    tg_app = build_application()
    set_application(tg_app)

    await tg_app.initialize()

    if settings.telegram_webhook_url and settings.environment == "production":
        await tg_app.bot.set_webhook(
            url=f"{settings.telegram_webhook_url}",
            allowed_updates=["message", "callback_query"],
        )
        await tg_app.start()
        yield
        await tg_app.stop()
        await tg_app.shutdown()
    else:
        await tg_app.start()
        poll_task = asyncio.create_task(_run_polling(tg_app))
        yield
        poll_task.cancel()
        await tg_app.stop()
        await tg_app.shutdown()


async def _run_polling(tg_app):
    """Polling mode per sviluppo locale."""
    await tg_app.updater.start_polling(drop_pending_updates=True)


app = FastAPI(
    title="Fitness Tracker API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meals.router)
app.include_router(activities.router)
app.include_router(health.router)
app.include_router(strava.router)
app.include_router(dashboard.router)
app.include_router(training.router)
app.include_router(webhook.router)
app.include_router(exercises_router)

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(os.path.join(frontend_path, "index.html"))


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}
