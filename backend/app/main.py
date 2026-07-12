from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fina ETF Research API",
        version="0.1.0",
        description="Backend API and automation for China-listed ETF rotation research.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api")

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- Serve frontend (after API routes so /api/* takes priority) ---
    @app.get("/", include_in_schema=False)
    def serve_index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    if FRONTEND_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")

    return app


app = create_app()
