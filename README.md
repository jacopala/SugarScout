# SugarScout — Pediatric Health Companion

A web app that supports a child with type 1 diabetes. A friendly companion checks in with the child, takes snack logs and live CGM readings, reminds them about care-plan tasks, and escalates to a parent when something needs attention. Parents get a separate dashboard.

The full design is in *Pediatric Health Companion: Design Document and Implementation Plan* (v0.2). This repository is at **Phase 1: Skeleton and data layer**.

## Core safety principles

These rules govern every change to this codebase (design doc Section 2):

1. **The LLM never decides safety-critical actions.** Alerts and reminders for glucose thresholds, missing data, and missed check-ins come from a deterministic rules engine. The LLM words messages and surfaces soft signals; it does not trigger emergencies on its own.
2. **No medical advice from the model.** The companion can relay the care plan the parent configured (for example, "it is time for your lunch insulin"). It cannot suggest doses, changes, or diagnoses.
3. **Fail loudly.** If CGM data stops arriving, the system alerts the parent. Silence is never treated as "fine."
4. **Emergency language bypasses the chat model.** Phrases indicating severe symptoms, self-harm, or abuse trigger a scripted child response and immediate parent escalation.
5. **Everything is auditable.** Every alert decision records which rule fired, which data it used, and what was sent.
6. **Parents stay in control.** Thresholds, contacts, quiet hours, and escalation timing are parent-configured, ideally with guidance from the child's care team.

> This software is not a medical device and is not a replacement for the CGM's own alerts.

## Layout

| Path | What it is |
| --- | --- |
| `backend/` | Python 3.13 package `sugarscout`: FastAPI API, ARQ worker, SQLAlchemy models, Alembic migrations |
| `backend/alembic/versions/0001_*` | `glucose_readings` hypertable, `glucose_hourly` / `glucose_daily` continuous aggregates, columnstore policy |
| `backend/tests/` | Health, migration, and Section 18.6 query-budget tests |
| `backend/scripts/rtt.py` | Database round-trip-time probe for choosing the Tiger Cloud region |
| `frontend/` | React + TypeScript (Vite, React Router, TanStack Query). Separate `/child` and `/parent` route trees |
| `docker-compose.yml` | Local TimescaleDB, Redis, API, worker, and a `migrate` tool service |
| `render.yaml` | Render Blueprint: API, worker, Redis (paid, always-on) |
| `frontend/vercel.json` | Vercel SPA config |

## Local development

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22+.

Start the database and Redis, then apply the migrations:

```bash
docker compose up -d timescaledb redis
```

```bash
docker compose run --rm migrate
```

Start the API (http://localhost:8000) and the worker:

```bash
docker compose up -d --build api worker
```

Start the frontend at http://localhost:5173. It proxies `/api` to the API:

```bash
npm --prefix frontend install && npm --prefix frontend run dev
```

Seed some readings to look at (3 children, 30 days, every 5 minutes):

```bash
docker compose exec api python -m sugarscout.dev.seed --children 3 --days 30
```

TimescaleDB is published on host port **55432** so it doesn't clash with a locally installed Postgres. Override it with `TSDB_HOST_PORT`. To run the backend outside Docker, copy `.env.example` to `backend/.env` and use `uv run …`.

### Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Backend tests create and drop a throwaway `sugarscout_test` database and use Redis DB 15. The test run prints a **Section 18.6 query budget** table.

## Pinned versions

The TimescaleDB version must be identical in all three places (design doc Section 19.5):

| Component | Version | Where |
| --- | --- | --- |
| TimescaleDB | **2.30.2 on PostgreSQL 17** | `docker-compose.yml`, `.github/workflows/ci.yml`, Tiger Cloud service |
| Redis | 7.4.6 | `docker-compose.yml`, CI |
| Python | 3.13 (image `python:3.13.16-slim-bookworm`) | `backend/.python-version`, `backend/Dockerfile` |
| Node | 22 LTS | `.nvmrc` |

Migration `0001` uses the `enable_columnstore` / `add_columnstore_policy` syntax. If the Tiger Cloud service runs a different TimescaleDB version, align the pins before running migrations against it.

## Data layer notes

- **Glucose bands** in the aggregates (`<54`, `54–69`, `70–180`, `181–250`, `>250` mg/dL) are the design doc's placeholders. **Confirm them with the care team before the pilot.** Changing them later means recreating both aggregates in a new migration.
- `glucose_hourly` also stores `sum_mg_dl`, so `glucose_daily` can compute an exact reading-weighted mean rather than an average of hourly averages.
- Both aggregates run in real-time mode (`materialized_only = false`), so the current hour includes the newest readings. Refresh policies cover the last 3 days (hourly) and 7 days (daily). **Any backfill older than that needs** `sugarscout.dev.seed.refresh_aggregates` (or `CALL refresh_continuous_aggregate`) afterwards.
- Readings older than 30 days move to the columnstore, segmented by `child_id`.
- The rules engine (Phase 4) must read **raw** `glucose_readings`, never the aggregates (Section 18.5).
- The worker writes `worker:heartbeat` to Redis every minute, but only after a successful database query. `/readyz` reports its age. Phase 4 adds the dead-man's switch that pages on a stale heartbeat.

## Deploying (manual steps)

Nothing has been provisioned yet. These steps need your accounts:

1. **Tiger Cloud.** Create a staging service on TimescaleDB 2.30.2 / PG 17 in the AWS region you chose in Phase 0. Copy its connection string, or its pooler URL if you use the pooler.
2. **Render.** Create a Blueprint from this repository (`render.yaml`). Choose the Render region that matches Tiger Cloud and edit `region:` if needed. Set the secrets:
   - `DATABASE_URL` on the `sugarscout-shared` env group.
   - `CORS_ORIGINS` on the API (the Vercel URL).

   Migrations run as the API's pre-deploy command.
3. **Vercel.** Import the repository with root directory `frontend`, and set `VITE_API_BASE_URL` to the Render API URL.
4. **Check.** `GET https://<api>/readyz` should return `"status": "ok"` with a recent worker heartbeat.

## Phase 1 gate

- [x] Migrations run cleanly and round-trip locally (`test_migrations.py`)
- [x] Query budgets pass locally (all well under 1 ms of execution time)
- [x] API, worker, and frontend run end to end locally
- [ ] Migrations run cleanly on the **Tiger Cloud staging** service
- [ ] Measured query times meet Section 18.6 targets **on staging**:
  ```bash
  TEST_DATABASE_URL=<staging url> TEST_EXTERNAL_DB=1 DB_SSL_MODE=require uv run pytest -m budget
  ```
- [ ] Round-trip time recorded from Render in each candidate region: `uv run python scripts/rtt.py` from a Render shell
- [ ] Hello-world deployments live on Vercel and Render staging

Record staging measurements here:

| Date | Region | RTT p50 / p95 | Rules query exec / wall | Month view exec / wall |
| --- | --- | --- | --- | --- |
| | | | | |
