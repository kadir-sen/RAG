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

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.config import CORS_ORIGINS
from backend.core.lifespan import lifespan
from backend.api import (
    admin,
    admin_jargon,
    admin_users,
    auth,
    chat,
    chronology,
    conversations,
    feedback,
    forensic,
    files,
    documents,
    indexing,
    library,
    knowledge,
    projects,
    reports,
    runs,
    usage,
)
from backend.core.security import get_current_user, require_admin
from backend.core.projects import get_current_project
from src.usage_tracker import BudgetExceededError
from src.user_store import UserQuotaExceededError, get_user_store
from src.billing_store import CreditBalanceExceededError, StorageQuotaExceededError

# Frontend build directory (exists only in Docker / after npm run build)
_frontend_dist = Path(_project_root) / "frontend" / "dist"


def _resolve_frontend_file(full_path: str, root: Path | None = None) -> Path | None:
    """Resolve a Vite public asset without allowing traversal outside dist."""
    dist_root = (root or _frontend_dist).resolve()
    candidate = (dist_root / full_path).resolve()
    if candidate.is_relative_to(dist_root) and candidate.is_file():
        return candidate
    return None


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

    # Compress every response > 500 B (JS bundle 462 KB → ~126 KB; CSS 47 KB
    # → ~8 KB). Big LCP win on cold loads. minimum_size avoids overhead on
    # tiny JSON payloads.
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # Hashed Vite assets are content-addressable, so we can mark them as
    # immutable for a year. Browsers skip the network entirely on revisits.
    class _AssetCacheHeaders(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            path = request.url.path
            if path.startswith("/assets/") and "." in path.rsplit("/", 1)[-1]:
                # Hashed Vite output → safe to cache forever.
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            elif path.endswith(".svg") or path == "/vite.svg":
                response.headers["Cache-Control"] = "public, max-age=604800"
            elif path in ("/", "/index.html", "/boot.js"):
                # SPA shell must not be cached (otherwise stale bundle hashes).
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
            return response

    app.add_middleware(_AssetCacheHeaders)

    auth_dep = [Depends(get_current_user)]
    project_dep = [Depends(get_current_project)]
    admin_dep = [Depends(require_admin)]

    # Public — login lives here, no auth required.
    app.include_router(auth.router, prefix="/api", tags=["auth"])
    app.include_router(projects.router, prefix="/api", tags=["projects"], dependencies=auth_dep)

    # Admin-only routers.
    app.include_router(
        admin_users.router, prefix="/api", tags=["admin"], dependencies=admin_dep,
    )
    app.include_router(admin.router, prefix="/api", tags=["admin"], dependencies=admin_dep)
    app.include_router(
        admin_jargon.router, prefix="/api", tags=["admin"], dependencies=admin_dep,
    )

    # Authenticated routers (chat already injects user explicitly; the router-
    # level dep is a belt-and-suspenders gate).
    app.include_router(chat.router, prefix="/api", tags=["chat"], dependencies=auth_dep + project_dep)
    app.include_router(
        chronology.router, prefix="/api", tags=["chronology"], dependencies=auth_dep,
    )
    app.include_router(
        conversations.router, prefix="/api", tags=["conversations"], dependencies=auth_dep + project_dep,
    )
    app.include_router(feedback.router, prefix="/api", tags=["feedback"], dependencies=auth_dep + project_dep)
    app.include_router(files.router, prefix="/api", tags=["files"], dependencies=auth_dep + project_dep)
    app.include_router(
        documents.router, prefix="/api", tags=["documents"], dependencies=auth_dep + project_dep,
    )
    app.include_router(
        indexing.router, prefix="/api", tags=["indexing"], dependencies=auth_dep + project_dep,
    )
    app.include_router(library.router, prefix="/api", tags=["library"], dependencies=auth_dep + project_dep)
    app.include_router(
        knowledge.router, prefix="/api", tags=["knowledge"], dependencies=auth_dep + project_dep,
    )
    app.include_router(reports.router, prefix="/api", tags=["reports"], dependencies=auth_dep + project_dep)
    app.include_router(forensic.router, prefix="/api", tags=["forensic"], dependencies=auth_dep)
    app.include_router(runs.router, prefix="/api", tags=["runs"], dependencies=auth_dep + project_dep)
    # Global usage (cost across the whole tenant) is operational data — admin-only.
    app.include_router(usage.router, prefix="/api", tags=["usage"], dependencies=admin_dep)

    # Pre-warm UserStore so the SQLite schema is created at startup.
    get_user_store()

    @app.exception_handler(BudgetExceededError)
    async def _budget_exceeded_handler(_req: Request, exc: BudgetExceededError):
        # HTTP 402 — payment required: signals to the UI that the global LLM
        # budget for this application has been spent.
        return JSONResponse(status_code=402, content={"detail": str(exc), "error": "budget_exceeded"})

    @app.exception_handler(UserQuotaExceededError)
    async def _user_quota_handler(_req: Request, exc: UserQuotaExceededError):
        return JSONResponse(
            status_code=402,
            content={
                "detail": str(exc),
                "error": "token_quota_exceeded",
                "used_tokens": exc.used,
                "token_limit": exc.limit,
                "percent_remaining": 0.0,
            },
        )

    @app.exception_handler(CreditBalanceExceededError)
    async def _credit_exceeded_handler(_req: Request, exc: CreditBalanceExceededError):
        return JSONResponse(
            status_code=402,
            content={"detail": str(exc), "error": "credit_balance_exhausted",
                     "credits_remaining": 0.0, "credit_percent_remaining": 0.0},
        )

    @app.exception_handler(StorageQuotaExceededError)
    async def _storage_exceeded_handler(_req: Request, exc: StorageQuotaExceededError):
        return JSONResponse(
            status_code=413,
            content={"detail": str(exc), "error": "storage_quota_exceeded",
                     "storage_used_bytes": exc.used, "storage_limit_bytes": exc.limit,
                     "attempted_bytes": exc.attempted},
        )

    from src.provider_credentials import ProviderCredentialError

    @app.exception_handler(ProviderCredentialError)
    async def _provider_credential_handler(_req: Request, _exc: ProviderCredentialError):
        # Do not expose filesystem paths, aliases or provider key material.
        return JSONResponse(
            status_code=503,
            content={
                "detail": "The dedicated AI service credential is unavailable.",
                "error": "provider_credential_unavailable",
            },
        )

    @app.get("/api/health", tags=["health"])
    async def health():
        try:
            from src.chronology_prompts import validate_chronology_runtime
            validate_chronology_runtime()
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={"status": "unhealthy", "component": "chronology", "error": str(exc)},
            )
        return {"status": "ok", "chronology": "ready"}

    # Serve React frontend in production
    if _frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve Vite public files, then fall back to the React SPA shell."""
            if full_path.startswith("api/"):
                from fastapi import HTTPException
                raise HTTPException(404, "Not found")
            static_file = _resolve_frontend_file(full_path)
            if static_file is not None:
                return FileResponse(str(static_file))
            return FileResponse(str(_frontend_dist / "index.html"))

    return app


app = create_app()
