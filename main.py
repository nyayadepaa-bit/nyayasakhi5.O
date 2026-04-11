"""
NyayaDepaaAI Auth — FastAPI entry point.

Production:  uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4
Dev:         uvicorn main:app --reload --port 8001
"""

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from config import get_settings
from database import init_db, async_session
from models import User
from utils.security import hash_password
from utils.rate_limiter import limiter
from utils.cache import close_redis
from middleware.error_logging import StructuredLoggingMiddleware, register_exception_handlers
from routes.auth_routes import router as auth_router
from routes.user_routes import router as user_router
from routes.admin_routes import router as admin_router
from routes.ai_routes import router as ai_router
from routes.chat_routes import router as chat_router

# ── Logging setup ─────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("NyayaDepaaAI")

settings = get_settings()


async def seed_admin():
    """Create default admin account if it doesn't exist."""
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == settings.ADMIN_EMAIL))
        if result.scalar_one_or_none():
            logger.info(f"Admin account already exists: {settings.ADMIN_EMAIL}")
            return
        admin = User(
            name=settings.ADMIN_NAME,
            email=settings.ADMIN_EMAIL,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        logger.info(f"✓ Admin account seeded: {settings.ADMIN_EMAIL}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 55)
    logger.info(f"  {settings.APP_NAME} — starting")
    logger.info("=" * 55)
    try:
        await init_db()
        await seed_admin()
        logger.info("✓ Database tables ready, connection pool active")
    except Exception as exc:
        if settings.ALLOW_START_WITHOUT_DB:
            logger.warning(f"Database startup skipped: {exc}")
            logger.warning("Running in degraded mode without database-dependent features")
        else:
            raise
    yield
    await close_redis()
    logger.info("Shutting down…")


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    lifespan=lifespan,
)

# ── Rate Limiting ─────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Structured Logging Middleware ─────────────────────
app.add_middleware(StructuredLoggingMiddleware)

# ── CORS ──────────────────────────────────────────────
_default_origins = [
    settings.FRONTEND_URL,
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
# Merge with comma-separated ALLOWED_ORIGINS from env (for Vercel / prod)
if settings.ALLOWED_ORIGINS:
    _default_origins += [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]


def _origin_with_host_variant(origin: str) -> list[str]:
    """Return origin plus www/non-www variant when applicable."""
    try:
        parsed = urlparse(origin)
        if not parsed.scheme or not parsed.netloc:
            return [origin]
        host = parsed.netloc
        if host.startswith("www."):
            return [origin, f"{parsed.scheme}://{host[4:]}"]
        return [origin, f"{parsed.scheme}://www.{host}"]
    except Exception:
        return [origin]


expanded_origins: list[str] = []
for origin in _default_origins:
    expanded_origins.extend(_origin_with_host_variant(origin))

allow_origin_regex = None
if any("vercel.app" in origin for origin in expanded_origins):
    allow_origin_regex = r"https://([a-zA-Z0-9-]+\.)*vercel\.app"

allowed_origins = list(dict.fromkeys(expanded_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception Handlers ───────────────────────────────
register_exception_handlers(app)

# ── Routers ───────────────────────────────────────────
app.include_router(auth_router, prefix="/api")
app.include_router(user_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(chat_router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": "2.0.0"}
