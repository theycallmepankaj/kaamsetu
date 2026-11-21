# KaamSetu

A voice-first job platform that connects blue-collar workers (electricians, plumbers, painters, masons, drivers, house help and others) with nearby employers across India. It works in Hindi and English.

```
Main_Project/
├── backend/    Python: FastAPI + Socket.IO + JWT auth + RAG assistant (Claude)
└── frontend/   JavaScript: React (Vite) + socket.io-client
```

## Features

| Feature | Where |
|---|---|
| Phone + password sign-up, worker or employer role | `backend/app/routers/auth.py`, `frontend/src/pages/Auth.jsx` |
| Voice profile: the worker speaks, and skills, experience, city and wage are filled in | `backend/app/rag/profile_parser.py`, `frontend/src/pages/WorkerProfile.jsx` |
| Nearby jobs by GPS distance (or same city) | `backend/app/routers/jobs.py` |
| **Live alerts** (Socket.IO): new job nearby, new application, hired, on the way, arrived | `backend/app/realtime.py`, `frontend/src/components/LiveAlerts.jsx` |
| **Live chat** between employer and hired worker, with typing indicator | `realtime.py`, `frontend/src/pages/Chat.jsx` |
| **RAG assistant**: answers about wages, unpaid dues, e-Shram, PM-SYM pension and construction board, with sources, streamed token by token | `backend/app/rag/`, `frontend/src/pages/Assistant.jsx` |
| Ratings after work is completed | `jobs.py`, `frontend/src/components/RateBox.jsx` |
| **Dashboards**: worker earnings, jobs done, rating, profile completeness; employer new applications, open jobs, active workers, amount paid | `backend/app/routers/community.py`, `WorkerHome.jsx`, `EmployerHome.jsx` |
| **Notification bell**: every live alert is also saved, so users see what they missed while offline | `models.Notification`, `realtime.notify_user`, `components/NotificationBell.jsx` |
| **Find workers** (employers): search by name, city and skill, sorted by availability and rating | `community.py`, `pages/FindWorkers.jsx` |
| **Worker public profile**: rating breakdown, reviews (reviewer shown as "Sunita S."), jobs completed | `community.py`, `pages/WorkerPublic.jsx` |
| **Urgent jobs** shown first and highlighted; sort jobs by nearest, highest pay or newest | `jobs.py`, `PostJob.jsx`, `WorkerHome.jsx` |
| **Landing page** built from live data: job board, counts, skills board, official helplines | `/api/stats/public`, `pages/Landing.jsx` |

## Demo data

```bash
cd backend && .venv/bin/python seed.py
```

This **wipes the dev database** and fills it with fictional data: 47 workers and 12 employers across 8 cities, about 55 jobs, applications, chats, reviews and notifications. Every phone number is in the `90000xxxxx` range, so none can belong to a real person, and the script refuses to run when `ENV=production`.

| Demo login | Phone | Password |
|---|---|---|
| Worker: Ramesh Yadav, painter, Indore | 9000000001 | demo1234 |
| Employer: Sunita Sharma, Indore | 9000100001 | demo1234 |

In development, the login page has one-tap buttons that fill in these accounts.

Run `seed.py` again after changing the database models. While there are no Alembic migrations, it is the way to rebuild the schema.

## Run it locally

You need Python 3.12 and Node 20 or newer. This machine has them in `~/.local` (installed by `uv` and the Node tarball), so add that to your PATH first:

```bash
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$PATH"
```

**Backend** (terminal 1):

```bash
cd backend
uv venv --python 3.12 .venv            # first time only
uv pip install --python .venv -r requirements.txt   # first time only
cp .env.example .env                    # first time only, then edit it
.venv/bin/uvicorn app.main:app --reload --port 8000
```

**Frontend** (terminal 2):

```bash
cd frontend
npm install       # first time only
npm run dev
```

Open http://localhost:5173. Vite forwards `/api` and `/socket.io` to the backend, so the browser sees one site.

**Tests:** `cd backend && .venv/bin/python -m pytest -q`

### Turning on the AI assistant

Put a Claude API key in `backend/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Without a key, the assistant runs in **offline mode**: it still searches the knowledge base and quotes the best matching section, and the voice profile uses a keyword parser. With a key, Claude (`claude-opus-5-5` by default, set with `CLAUDE_MODEL`) writes a short answer in the user's language from the retrieved sections and cites them. The assistant uses low effort to keep answers fast and cheap. If a request is declined by a safety check, it falls back to another model on the server side.

### Adding knowledge

Add a Markdown file in `backend/app/rag/knowledge/`. The file starts with `title:`, `source:` and `audience:` (`all`, `worker` or `employer`). Each `## ` section becomes one searchable chunk. Add a `Keywords:` line with Hindi and Hinglish words so questions in those languages find it. Restart the server to pick up the change.

## Security

**Authentication**
- Passwords are hashed with bcrypt (cost 12), after SHA-256, so long passwords are not cut off at 72 bytes.
- The **access token** is a JWT (HS256, 15 minutes). It is pinned to one algorithm, and the issuer, audience, expiry and token type are all checked. It is kept only in memory in the browser, never in localStorage.
- The **refresh token** is a JWT in an `httpOnly`, `SameSite=Strict` cookie. It is `Secure` in production and limited to the `/api/auth` path. Each use **rotates** it. The server stores only a hash of each token, and if an old token is used again, the whole session family is revoked (this catches stolen tokens).
- "Log out everywhere" and changing your password bump `token_version`, which instantly cancels every access token already issued.
- **Brute force:** the account locks for 15 minutes after 5 wrong passwords. Login and register are also rate limited per IP. Unknown phone numbers take as long to check as real ones, so they can't be used to discover who has an account.

**Authorization**
- Every endpoint checks the role (worker or employer) and **ownership**. Another user's jobs, applications or chats return 404, so IDs can't be guessed.
- Each side may only make the status changes allowed for it (for example, only the employer can mark work completed).
- The worker's phone number is shown to the employer only after hiring.

**Socket.IO**
- A connection is refused without a valid access token. The token is checked again on each chat and assistant event, so a revoked session can't keep using an open socket.
- Users join only their own rooms and chats they take part in. Messages are capped in size and rate limited (30 chat messages and 10 assistant questions per minute).

**Input and HTTP**
- Strict Pydantic models reject unknown fields, enforce lengths and ranges, validate Indian mobile numbers, check GPS coordinates against India's bounds, and strip control characters.
- CORS allows only the configured origin (with credentials). Cookie endpoints also check the `Origin` header to block CSRF.
- Security headers on every response: CSP, X-Frame-Options, nosniff, Referrer-Policy, and HSTS in production. Requests over 256 KB are rejected. API docs are hidden in production. Errors never return stack traces.
- The assistant is told never to ask for an OTP, UPI PIN, bank password or Aadhaar number.

## Going to production (checklist)

1. In `backend/.env`, set `ENV=production`, a random `JWT_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(64))"`), `ALLOWED_HOSTS` and `FRONTEND_ORIGINS=https://yourdomain.in`. The server refuses to start with the dev secret.
2. Use PostgreSQL (`DATABASE_URL=postgresql+psycopg://...`, and `pip install psycopg[binary]`) and manage the schema with Alembic.
3. Serve everything from **one domain over HTTPS**. Put `npm run build` output (`frontend/dist`) behind nginx and proxy `/api` and `/socket.io` (with WebSocket upgrade) to uvicorn. Add a CSP for the frontend in nginx, for example: `default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self' wss://yourdomain.in`.
4. To run several backend processes, set `REDIS_URL` (Socket.IO then shares rooms through Redis) and give the rate limiter Redis storage (`backend/app/limiter.py`).
5. Run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>` so rate limits see real client IPs.
6. Host in an Indian region (DPDP Act 2023), and add a privacy policy, a consent screen and account deletion.

## Next steps

- OTP login via an SMS provider (MSG91, Twilio) in addition to passwords
- A WhatsApp bot that uses the same backend
- More languages (Bhashini or AI4Bharat for translation and speech)
- Multilingual embeddings and pgvector in place of BM25 for search
- Map view of jobs, and verification of e-Shram registration
