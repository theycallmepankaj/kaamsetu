import logging

import socketio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .config import get_settings
from .database import Base, engine
from .limiter import limiter
from .realtime import sio
from .routers import auth, community, jobs, profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()

# For production, manage schema changes with Alembic migrations instead.
Base.metadata.create_all(bind=engine)

api = FastAPI(
    title="KaamSetu API",
    version="1.0.0",
    # Hide interactive docs in production
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)

api.state.limiter = limiter
api.add_middleware(SlowAPIMiddleware)
api.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,  # never "*" when cookies are used
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
if settings.is_production:
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts)


@api.middleware("http")
async def security_headers(request: Request, call_next):
    # Reject very large bodies early (all our JSON inputs are small)
    if int(request.headers.get("content-length") or 0) > 256 * 1024:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    if not request.url.path.startswith("/api/docs"):
        h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    h["Cache-Control"] = "no-store"
    if settings.is_production:
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return response


@api.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": "Too many requests. Please wait and try again."}, status_code=429)


@api.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logging.getLogger("kaamsetu").exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Something went wrong"}, status_code=500)  # never leak stack traces


@api.get("/api/health")
def health():
    return {"status": "ok"}


api.include_router(auth.router)
api.include_router(profile.router)
api.include_router(jobs.router)
api.include_router(community.router)

# One ASGI app serves both REST (/api/...) and Socket.IO (/socket.io/...)
app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
