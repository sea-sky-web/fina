from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

MUTATION_PREFIXES = ("/api/refresh", "/api/factors/rebuild", "/api/portfolio")


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

    @app.middleware("http")
    async def api_key_guard(request: Request, call_next):
        if settings.api_key and request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if any(request.url.path.startswith(p) for p in MUTATION_PREFIXES):
                provided = request.headers.get("X-API-Key", "")
                if provided != settings.api_key:
                    return JSONResponse(status_code=403, content={"detail": "Invalid or missing API key"})
        return await call_next(request)

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
