"""FastAPI application factory."""

import sys
from pathlib import Path

# Ensure project root is on sys.path so `from src.*` imports work
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv(Path(_project_root) / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.core.config import CORS_ORIGINS
from backend.core.lifespan import lifespan
from backend.api import admin, chat, conversations, files, documents, indexing, library, knowledge

# Frontend build directory (exists only in Docker / after npm run build)
_frontend_dist = Path(_project_root) / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Document Analysis Platform",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(conversations.router, prefix="/api", tags=["conversations"])
    app.include_router(files.router, prefix="/api", tags=["files"])
    app.include_router(documents.router, prefix="/api", tags=["documents"])
    app.include_router(indexing.router, prefix="/api", tags=["indexing"])
    app.include_router(library.router, prefix="/api", tags=["library"])
    app.include_router(knowledge.router, prefix="/api", tags=["knowledge"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])

    @app.get("/api/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    # Serve React frontend in production
    if _frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve React SPA — all non-API routes return index.html."""
            if full_path.startswith("api/"):
                from fastapi import HTTPException
                raise HTTPException(404, "Not found")
            return FileResponse(str(_frontend_dist / "index.html"))

    return app


app = create_app()
