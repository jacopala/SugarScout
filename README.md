# SugarScout — Pediatric Health Companion

A web app that supports a child with type 1 diabetes. A friendly companion checks in with the child, takes snack logs and live CGM readings, reminds them about care-plan tasks, and escalates to a parent when something needs attention. Parents get a separate dashboard.

The full design is in *Pediatric Health Companion: Design Document and Implementation Plan* (v0.2). This repository is a **hackathon build**: CGM data is simulated, there's one demo child, and a shared access code stands in for sign-in.

## Hackathon demo

### What's real and what's simulated

| Piece | Status |
| --- | --- |
| Glucose data | **Fake CGM** in the worker: one reading every 5 s with real timestamps, sped-up dynamics, and presenter-controlled scenarios |
| Rules and alerts | Real: deterministic rules on raw readings (low, urgent low, high, **rapid drop**, **rapid rise**), dedupe, auto-resolve, and an audit trail ("Why did this fire?") |
| Parent alerts | **Browser push** with the real message about the child. Every alert goes to the dashboard and to push. On iPhone, add the parent page to the Home Screen first. A push is sent the moment its alert is raised, typically within 0.25 s. SMS via a Twilio trial is an urgent-only backup and can only send Twilio's canned template text |
| Parent dashboard | Live chart with the forecast, an **alerts bell** with a pop-up inbox, a sandwich menu for sections, a mood summary, and a compact **Scout agent** card. The card shows only the latest decision until the parent taps **Show reasons and history** |
| Forecast | ~20-minute trend forecast on every reading, scored against what happened. It drives *low soon*, *urgent low soon* and *high soon* alerts |
| Scout agent | Nemotron chooses which allowed question to ask and drafts non-urgent heads-ups; fixed rules make every urgent decision |
| Insulin | Parents log doses (record-only); the child can answer "did you have your insulin?". Never calculated or suggested |
| Scout (child) | Voice-first display: say "Hey Scout", then talk. Speech recognition is **Riva Parakeet** and Scout's voice is **Magpie TTS**, both on NVIDIA's cloud. Replies come from Nemotron 3.5 Lightning, with a deterministic emergency bypass and an output filter. Typing is the fallback |
| Mood check-in | The child's landing page asks "How are you feeling today?" (1–5). Each answer is saved with its time and shown to the parent. Scout replies with a fixed gentle line. A happy face (4–5) sets off fireworks. The saddest face makes Scout offer a call to their grown-up. Moods never alert the parent on their own |
| Worried words | Every child message (typed or spoken) gets a deterministic **concern score**, with no model involved (`ai/concern.py`). Mild: Scout answers gently. Moderate: Scout suggests calling their grown-up and shows a **call card** (call, *Ask them to come*, or *I'm okay*). High: the parent also gets a non-urgent *worried words* alert. Emergencies still go through the separate emergency bypass |
| Fun | Tap Scout's face for **fireworks**. **Play** opens *Sky Pop*, a 30-second bubble-popping game: you can't lose, it saves your best score on the device, and Help and care reminders stay on screen while you play |
| Parent summary | Real: Nemotron Super words stats that were computed in code. The output is validated and rejected if unsafe |
| Sign-in | Replaced by one `DEMO_ACCESS_CODE` |

### How the Scout agent works

Every 15 seconds (and right after a meal, insulin entry or answer), SugarScout:

1. **Builds the situation in code:** glucose, a ~20-minute trend forecast (and how accurate past forecasts were), meals and their estimated carbs, insulin timing, moods, open alerts, and a concern level (0–2) with reasons.
2. **Applies fixed rules:**
   - thresholds;
   - *rapid drop*: −25 mg/dL across 4 readings;
   - *rapid rise*: +30 mg/dL across 4 readings, so a climb alerts early instead of only at 250;
   - *low soon*, *urgent low soon* and *high soon* from the forecast;
   - *symptoms reported*: the child says shaky or dizzy while low or falling.

   These rules are the only things that send urgent alerts.
3. **Asks Nemotron to advise:** pick one question from the questions allowed right now (how do you feel, did you have insulin with your snack, when did you last eat, how do you feel after eating, daily mood), word it for a child, and optionally draft a non-urgent heads-up for the parent.
4. **Enforces guardrails:** a question that isn't allowed, child wording with numbers or medical advice, a heads-up without concern, or dosing advice is overridden. Every decision is stored with a short reason and shown on the parent's **Scout agent** timeline.

Why no ML prediction model: there's no real patient data to train or validate one, and a learned predictor would be a medical device. The forecast is the same idea CGMs use for "urgent low soon": a trend line, scored against what actually happened.

### Demo script (about 5 minutes)

Open `/parent` on the laptop (tap **Alert me on this device** once, and allow notifications) and `/child` in **Chrome** on a phone or second screen.

1. **Daily check-in.** On the child view, tap a happy face on the mood bar, then **That's me**. Fireworks go off and Scout says a gentle line. The parent sees the mood with the time.
2. **Voice.** Tap the mic and say *"Tell me a joke."* Double-tap the mic to stop listening.
3. **Snack, no insulin.** Under Demo controls click **Big snack, no insulin** (or have the child log a meal). Glucose climbs, and a **rapid rise** alert arrives well before 250. Scout asks *"Did you have your insulin with your snack?"* out loud. The parent's phone gets a **push heads-up** with the facts (glucose, carbs, no insulin logged). Answer **Not yet**.
4. **Parent logs insulin** on the Insulin card. The rise flattens on the live chart (dashed line = forecast).
5. **Low soon.** Click **Rapid drop**. Before glucose crosses 70, an **urgent low soon** push arrives with the forecast. Scout asks *"How do you feel right now?"* Tap **Shaky**: a rule escalates with Alex's own words in the push.
6. **Worried words.** Type or say *"I'm really scared and I want my mom."* Scout answers kindly and shows the **call card**. The parent gets a *worried words* alert.
7. **Help button.** On the child view tap **Help**, then **Yes, get help**. The parent's push says Alex needs them; tap **I'm on my way**.
8. **A break.** Tap **Play** for a round of Sky Pop, or tap Scout's face for fireworks.
9. **Timeline and summary.** On the Scout agent card, tap **Show reasons and history** to show each question, answer and heads-up with its reason. Then tap **Generate summary**.

Pitch line: *the AI talks; fixed rules decide.*

### Running the demo (laptop + HTTPS tunnel)

The demo runs on one laptop. Phones need HTTPS for push notifications and the microphone, so a free Cloudflare quick tunnel gives the laptop an `https://….trycloudflare.com` address. You don't need an account or a deploy.

**One-time setup**

1. Install `cloudflared`:

   ```bash
   brew install cloudflared
   ```

2. Copy `.env.example` to `backend/.env`.
3. Fill in `DEMO_ACCESS_CODE`, `NVIDIA_API_KEY`, the Twilio keys and `PARENT_PHONE`.
4. Generate a VAPID key pair for `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY`:

   ```bash
   cd backend && uv run python scripts/vapid.py
   ```

5. On the first run, create the tables:

   ```bash
   docker compose up -d timescaledb redis && docker compose run --rm migrate
   ```

Docker Compose loads `backend/.env` into the containers. The tests ignore it, and git ignores it.

**Start everything** (from the repository root)

1. Start the backend: database, Redis, API and worker.

   ```bash
   docker compose up -d
   ```

2. Build the frontend and serve the build on port 4173:

   ```bash
   npm --prefix frontend run build && npm --prefix frontend run preview -- --port 4173
   ```

3. In a second terminal, open the tunnel:

   ```bash
   cloudflared tunnel --url http://localhost:4173
   ```

4. Open the `https://….trycloudflare.com` link that `cloudflared` prints. Use `/parent` on the parent's phone and `/child` on the child's, then enter the access code. On iPhone, add the parent page to the Home Screen before turning on alerts.

Each run of `cloudflared` gives a new link. If a phone shows **Error 1033**, the tunnel has stopped: run step 3 again and use the new link. `vite preview` forwards `/api` to the API on port 8000, so the phone only ever talks to the tunnel.

**Shut everything down**

1. Press `Ctrl-C` in the `cloudflared` terminal.
2. Press `Ctrl-C` in the `preview` terminal.
3. Stop the containers:

   ```bash
   docker compose down
   ```

Don't add `-v` to `docker compose down`: it deletes the database volume.

**Before you present**

- `http://localhost:8000/readyz` returns `"status": "ok"` with a recent worker heartbeat.
- The dashboard's Demo controls show **SMS: live · AI: on**.
- You've run the demo script once end to end.

The repository still includes `render.yaml` and `frontend/vercel.json` for a hosted deployment later. The demo doesn't use them: Render can't be used for this repository.

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
| `backend/alembic/versions/` | `0001` glucose hypertable, continuous aggregates and columnstore policy. `0002`–`0006` add the demo core, mood check-ins, meals, the Scout agent and the alerts inbox |
| `backend/src/sugarscout/rules/` | Deterministic rules engine: thresholds, rapid drop and rapid rise, forecast rules |
| `backend/src/sugarscout/agent/` | Scout agent loop: situation, allowed questions, guardrails |
| `backend/src/sugarscout/ai/` | Chat and voice, emergency bypass (`safety.py`), concern scoring (`concern.py`), parent summary |
| `backend/src/sugarscout/notify/` | Web push through a push outbox. Rows are claimed with `SKIP LOCKED`, so an instant send and the 2 s sweep never double-send. Also Twilio SMS |
| `backend/src/sugarscout/api/http_cache.py` | Weak ETag / `304 Not Modified` for polling, plus gzip |
| `backend/tests/` | Rules, agent, forecast, concern, chat, voice, push, HTTP cache, insulin, migration and Section 18.6 query-budget tests |
| `backend/scripts/` | `vapid.py` (push keys) and `rtt.py` (database round-trip probe) |
| `frontend/` | React + TypeScript (Vite, React Router, TanStack Query). Separate `/child` and `/parent` route trees. `/child/play` is Sky Pop |
| `docker-compose.yml` | Local TimescaleDB, Redis, API, worker, and a `migrate` tool service |
| `.claude/launch.json` | Preview configurations: `frontend` (5173), `frontend-wifi` (5175, on the LAN), `frontend-demo` (preview build on 4173, for the tunnel) |
| `render.yaml`, `frontend/vercel.json` | Hosted-deploy configs. The demo doesn't use them |

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

To try it on a phone on the same Wi-Fi, run the dev server on your local network and open `http://<laptop-ip>:5175`:

```bash
npm --prefix frontend run dev -- --host --port 5175
```

Plain HTTP can't use push or the microphone, so use the tunnel above for those.

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
- **Latency and data use:** after an event or heads-up, the API queues an instant `push_now` job, and the 2 s outbox sweep is the fallback. Dashboard polling (every 3 s) uses weak ETags, so unchanged data comes back as `304` with no body, and the rest is gzipped. That took the parent dashboard from about 68 MB/h to about 1.8 MB/h.
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
