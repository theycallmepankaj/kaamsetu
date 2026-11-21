"""Socket.IO server: live job alerts, worker-employer chat and the streaming assistant.

Every connection must present a valid access token; it is checked again on each
sensitive event so a revoked session cannot keep using an open socket.
"""

import json
import time
from collections import defaultdict, deque

import socketio
from fastapi import HTTPException

from .config import get_settings
from .database import SessionLocal
from .models import Application, Message, Notification, User
from .security import user_from_access_token

settings = get_settings()

_manager = socketio.AsyncRedisManager(settings.redis_url) if settings.redis_url else None
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.origins,
    client_manager=_manager,
    max_http_buffer_size=64 * 1024,  # reject huge payloads
    ping_interval=25,
    ping_timeout=20,
)


def _room(user_id: int) -> str:
    return f"user:{user_id}"


async def notify_user(user_id: int, event: str, data: dict, link: str = "") -> None:
    """Save the alert (for the notification bell) and push it live if the user is online."""
    with SessionLocal() as db:
        n = Notification(user_id=user_id, kind=event, data=json.dumps(data, ensure_ascii=False), link=link)
        db.add(n)
        db.commit()
        db.refresh(n)
        item = {"id": n.id, "kind": n.kind, "data": data, "link": n.link, "read": False, "created_at": n.created_at.isoformat()}
    await sio.emit(event, data, room=_room(user_id))
    await sio.emit("notification:new", item, room=_room(user_id))


# ---------- simple per-user rate limiter ----------


class _Bucket:
    def __init__(self, limit: int, per_seconds: int):
        self.limit, self.per = limit, per_seconds
        self.hits: dict[int, deque] = defaultdict(deque)

    def allow(self, key: int) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.per:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


_chat_limit = _Bucket(limit=30, per_seconds=60)
_bot_limit = _Bucket(limit=10, per_seconds=60)


# ---------- helpers ----------


async def _user(sid: str) -> User | None:
    session = await sio.get_session(sid)
    token = session.get("token")
    if not token:
        return None
    with SessionLocal() as db:
        try:
            return user_from_access_token(db, token)
        except HTTPException:
            return None


def _participant_app(db, app_id: int, user: User) -> Application | None:
    a = db.get(Application, app_id)
    if not a or (a.worker_id != user.id and a.job.employer_id != user.id):
        return None
    if a.status in ("rejected", "withdrawn"):
        return None
    return a


# ---------- events ----------


@sio.event
async def connect(sid, environ, auth):
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    if not token:
        raise socketio.exceptions.ConnectionRefusedError("unauthorized")
    with SessionLocal() as db:
        try:
            user = user_from_access_token(db, token)
        except HTTPException:
            raise socketio.exceptions.ConnectionRefusedError("unauthorized")
    await sio.save_session(sid, {"token": token, "user_id": user.id, "history": []})
    await sio.enter_room(sid, _room(user.id))


@sio.event
async def auth_refresh(sid, data):
    """Client sends its new access token after refreshing, so long-lived sockets stay valid."""
    token = (data or {}).get("token")
    if not isinstance(token, str):
        return {"ok": False}
    with SessionLocal() as db:
        try:
            user = user_from_access_token(db, token)
        except HTTPException:
            return {"ok": False}
    session = await sio.get_session(sid)
    if session.get("user_id") != user.id:
        return {"ok": False}
    session["token"] = token
    await sio.save_session(sid, session)
    return {"ok": True}


@sio.on("chat:join")
async def chat_join(sid, data):
    user = await _user(sid)
    if not user:
        return {"ok": False, "error": "unauthorized"}
    app_id = (data or {}).get("application_id")
    if not isinstance(app_id, int):
        return {"ok": False, "error": "bad request"}
    with SessionLocal() as db:
        if not _participant_app(db, app_id, user):
            return {"ok": False, "error": "not found"}
    await sio.enter_room(sid, f"app:{app_id}")
    return {"ok": True}


@sio.on("chat:leave")
async def chat_leave(sid, data):
    app_id = (data or {}).get("application_id")
    if isinstance(app_id, int):
        await sio.leave_room(sid, f"app:{app_id}")


@sio.on("chat:send")
async def chat_send(sid, data):
    user = await _user(sid)
    if not user:
        return {"ok": False, "error": "unauthorized"}
    if not _chat_limit.allow(user.id):
        return {"ok": False, "error": "Too many messages, slow down"}
    app_id = (data or {}).get("application_id")
    text = (data or {}).get("text")
    if not isinstance(app_id, int) or not isinstance(text, str):
        return {"ok": False, "error": "bad request"}
    text = text.strip()[:1000]
    if not text:
        return {"ok": False, "error": "empty"}
    with SessionLocal() as db:
        a = _participant_app(db, app_id, user)
        if not a:
            return {"ok": False, "error": "not found"}
        msg = Message(application_id=a.id, sender_id=user.id, text=text)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        other = a.job.employer_id if a.worker_id == user.id else a.worker_id
        payload = {
            "id": msg.id,
            "application_id": a.id,
            "sender_id": user.id,
            "sender_name": user.name,
            "text": msg.text,
            "created_at": msg.created_at.isoformat(),
        }
    await sio.emit("chat:message", payload, room=f"app:{app_id}")
    await notify_user(other, "chat:notify", {"application_id": app_id, "from": user.name, "text": text[:80]}, f"/chat/{app_id}")
    return {"ok": True}


@sio.on("chat:typing")
async def chat_typing(sid, data):
    session = await sio.get_session(sid)
    app_id = (data or {}).get("application_id")
    rooms = sio.rooms(sid)
    if isinstance(app_id, int) and f"app:{app_id}" in rooms:
        await sio.emit("chat:typing", {"application_id": app_id, "user_id": session["user_id"]}, room=f"app:{app_id}", skip_sid=sid)


@sio.on("bot:ask")
async def bot_ask(sid, data):
    from .rag.assistant import answer_stream  # local import avoids a cycle

    user = await _user(sid)
    if not user:
        await sio.emit("bot:error", {"error": "unauthorized"}, to=sid)
        return
    if not _bot_limit.allow(user.id):
        await sio.emit("bot:error", {"error": "Too many questions. Please wait a minute."}, to=sid)
        return
    question = (data or {}).get("message")
    lang = (data or {}).get("lang", "en")
    if not isinstance(question, str) or not question.strip():
        return
    question = question.strip()[:1000]
    lang = lang if lang in ("en", "hi") else "en"

    session = await sio.get_session(sid)
    history = session.get("history", [])[-6:]
    answer_parts: list[str] = []
    sources = []
    try:
        async for kind, value in answer_stream(question, history, lang, user.role):
            if kind == "token":
                answer_parts.append(value)
                await sio.emit("bot:token", {"text": value}, to=sid)
            elif kind == "sources":
                sources = value
    except Exception:
        await sio.emit("bot:error", {"error": "The assistant is unavailable right now. Please try again."}, to=sid)
        return
    answer = "".join(answer_parts).strip()
    if answer:  # never store an empty assistant turn; the API rejects those
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        session["history"] = history[-6:]
        await sio.save_session(sid, session)
    await sio.emit("bot:done", {"sources": sources}, to=sid)
