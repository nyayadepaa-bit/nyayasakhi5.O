# NyayaDepaaAI – Auth App v2.0

Full-stack authentication & AI query system for **~150 concurrent users** with monitoring, caching, and Docker deployment.

| Layer | Stack |
|-------|-------|
| Frontend | React 18 · Vite · Tailwind CSS · React Router · Axios |
| Backend | FastAPI · SQLAlchemy (async, pooled) · PostgreSQL (Neon) · JWT · bcrypt |
| Caching | Redis 7 (async, graceful fallback) |
| Rate Limiting | slowapi (per-endpoint) |
| Deployment | Docker Compose (4 services) · Nginx |

---

## What's New in v2.0

1. **Connection pooling** – AsyncAdaptedQueuePool (pool_size=20, max_overflow=30, pool_pre_ping)
2. **Rate limiting** – signup 3/min, login 5/min, AI query 20/min via slowapi
3. **AI query endpoint** – POST → background processing → poll for result
4. **Redis caching** – analytics cached 60 s, AI results cached on completion
5. **Enhanced admin analytics** – 7 stat cards + bar charts (users/day, queries/day)
6. **Activity monitoring** – filters (email, date range, action type) + pagination
7. **Admin audit logs** – every toggle/delete recorded with IP, viewable in dashboard
8. **Global error handling** – structured JSON errors for 404, 422, 500
9. **Structured logging** – every request logged (method, path, status, duration, user, IP)
10. **Docker deployment** – multi-stage build, Compose with postgres + redis + backend + nginx

---

## Features

- **Signup / Login** with JWT (access + refresh tokens), rate-limited
- **Email verification** via Resend SMTP
- **Role-based access** – User & Admin
- **User Dashboard** – profile edit, AI legal query with polling, activity log
- **Admin Dashboard** – analytics with charts, user management, activity monitoring (filtered + paginated), audit log tab
- **Auto-seeded admin** account on first startup
- **Graceful degradation** – works without Redis (caching skipped silently)

---

## Quick Start

### Option A: Docker (recommended)

```bash
cd auth_app
docker compose up --build -d
```

| Service | URL |
|---------|-----|
| Frontend (Nginx) | http://localhost |
| Backend API | http://localhost:8001 |

### Option B: Local Development

#### 1. Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL** (local or Neon cloud)
- **Redis** (optional, auto-skipped if unavailable)

#### 2. Backend

```bash
cd auth_app/backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -r requirements.txt

# Configure environment
copy ..\.env.example .env    # Windows
# cp ../.env.example .env    # macOS / Linux
# Edit .env with your credentials

uvicorn main:app --reload --port 8001
```

The backend starts at **http://localhost:8001**. On first run it creates all tables and seeds the admin.

#### 3. Frontend

```bash
cd auth_app/frontend
npm install
npm run dev
```

Opens at **http://localhost:5173**. Vite proxies `/api` calls to port 8001.

---

## Default Admin Credentials

| Field | Value |
|-------|-------|
| Email | `nyayadepaa@gmail.com` |
| Password | `Adminlogin@12345678` |

Change these in `.env` before deploying.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string (asyncpg) |
| `JWT_SECRET` | — | Secret key for JWT signing |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token TTL |
| `SMTP_HOST` | `smtp.resend.com` | SMTP server |
| `SMTP_PORT` | `465` | SMTP port |
| `SMTP_USER` | `resend` | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password / API key |
| `FROM_EMAIL` | — | Sender email address |
| `FRONTEND_URL` | `http://localhost:5173` | Frontend base URL (for email links) |
| `ADMIN_EMAIL` | — | Seeded admin email |
| `ADMIN_PASSWORD` | — | Seeded admin password |
| `ADMIN_NAME` | `Admin` | Seeded admin display name |
| `DB_POOL_SIZE` | `20` | SQLAlchemy pool size |
| `DB_MAX_OVERFLOW` | `30` | Extra connections beyond pool size |
| `DB_POOL_TIMEOUT` | `30` | Seconds to wait for a connection |
| `DB_POOL_RECYCLE` | `1800` | Recycle connections after N seconds |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `CACHE_TTL` | `60` | Default cache TTL in seconds |
| `RATE_LIMIT_LOGIN` | `5/minute` | Login rate limit |
| `RATE_LIMIT_SIGNUP` | `3/minute` | Signup rate limit |
| `RATE_LIMIT_AI_QUERY` | `20/minute` | AI query rate limit |

---

## API Endpoints

### Auth (`/api/auth`) — rate-limited
| Method | Path | Rate | Description |
|--------|------|------|-------------|
| POST | `/signup` | 3/min | Register new user |
| POST | `/login` | 5/min | User login → tokens |
| POST | `/admin/login` | 5/min | Admin-only login |
| POST | `/verify-email` | — | Verify email token |
| POST | `/refresh` | — | Refresh access token |

### User (`/api/user`) — requires Bearer token
| Method | Path | Description |
|--------|------|-------------|
| GET | `/me` | Get profile |
| PATCH | `/me` | Update name |
| POST | `/input` | Submit input (logged) |
| GET | `/activity` | Own activity history |

### AI (`/api/ai`) — requires Bearer token, rate-limited
| Method | Path | Rate | Description |
|--------|------|------|-------------|
| POST | `/query` | 20/min | Submit AI query (returns 202, processing in background) |
| GET | `/query/{id}` | — | Poll query status/result (cached when completed) |
| GET | `/queries` | — | Paginated query history for current user |

### Admin (`/api/admin`) — requires admin Bearer token
| Method | Path | Description |
|--------|------|-------------|
| GET | `/analytics` | Dashboard stats + chart data (cached 60 s) |
| GET | `/users` | List users (search, role filter) |
| GET | `/activity` | Paginated activity (email, date range, action type filters) |
| PATCH | `/users/{id}/toggle` | Enable/disable user (audit-logged) |
| DELETE | `/users/{id}` | Delete user (audit-logged) |
| GET | `/audit-log` | Admin action audit trail |

---

## Database Models

| Table | Key Columns |
|-------|-------------|
| `users` | id, email, name, password_hash, role, email_verified, is_active |
| `user_activity` | id, user_id, action_type, input_text, timestamp |
| `ai_queries` | id, user_id, input_text, response_text, tokens_used, latency_ms, status |
| `admin_actions` | id, admin_id, action, target_user_id, details, timestamp, ip_address |

---

## Folder Structure

```
auth_app/
├── Dockerfile               # Multi-stage (backend + frontend + nginx)
├── docker-compose.yml        # postgres + redis + backend + frontend
├── nginx.conf                # SPA fallback + /api proxy
├── .env.example
├── backend/
│   ├── main.py               # FastAPI entry (v2.0, logging, error handlers)
│   ├── config.py             # Settings (pooling, Redis, rate limits)
│   ├── database.py           # Async engine with connection pooling
│   ├── models.py             # User, UserActivity, AIQuery, AdminAction
│   ├── schemas.py            # 16 Pydantic schemas
│   ├── requirements.txt
│   ├── utils/
│   │   ├── security.py       # JWT + bcrypt
│   │   ├── email.py          # SMTP verification
│   │   ├── cache.py          # Redis async cache layer
│   │   └── rate_limiter.py   # slowapi limiter instance
│   ├── middleware/
│   │   ├── deps.py           # Auth dependencies (get_current_user, require_admin)
│   │   └── error_logging.py  # Structured logging + exception handlers
│   └── routes/
│       ├── auth_routes.py    # Signup, login, verify (rate-limited)
│       ├── user_routes.py    # Profile, input, activity
│       ├── admin_routes.py   # Users, analytics, activity, audit log
│       └── ai_routes.py      # AI query + background processing
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── index.css
        ├── api/
        │   └── axios.js       # API client + JWT interceptors
        ├── context/
        │   └── AuthContext.jsx
        ├── components/
        │   ├── Navbar.jsx
        │   ├── ProtectedRoute.jsx
        │   └── AdminRoute.jsx
        └── pages/
            ├── Login.jsx
            ├── Signup.jsx
            ├── VerifyEmail.jsx
            ├── AdminLogin.jsx
            ├── UserDashboard.jsx  # Profile + AI query + activity
            └── AdminDashboard.jsx # Charts + users + activity + audit log
```
