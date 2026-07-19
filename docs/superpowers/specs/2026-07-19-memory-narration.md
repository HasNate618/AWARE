# AWARE — Memory & Narration Spec

**Date:** 2026-07-19  
**Status:** Approved for implementation  
**Depends on:** [2026-07-18-aware-design.md](./2026-07-18-aware-design.md)  
**Target:** Hack The 6ix — Qualcomm Arduino UNO Q track (video + writeup submission)

---

## 1. Goal

Add an on-device **memory narration pipeline** so users can ask *"what happened in the last hour?"* and get a natural-language answer from local data — no cloud, no footage review.

This is **act three** of the existing pitch ("teach a rule → it executes → ask what happened"). It does not replace the "automate anything" headline.

### Success criteria

1. User types a question in the dashboard **Ask** card → receives an answer sourced from SQLite events + stored summaries.
2. A background task every **5 minutes** compresses recent events into a digest, optionally narrates via on-device LLM, and stores the result.
3. If the LLM is unavailable, summaries still appear using deterministic digest text (demo never breaks).
4. Event logging produces **narratable** data: enter/exit transitions and discrete sounds — not 500ms frame spam.
5. Sensors feel live on the dashboard (updates every few seconds) without flooding the event log.

---

## 2. Locked decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Perception logging | **B** — log `detection_enter` / `detection_exit` / discrete `sound` events; **drop** `perception` topic |
| 2 | Dashboard UX | Separate **Ask** card (not shared with Teach) |
| 3 | LLM unavailable | **A** — store digest as `narrative` when LLM fails or is absent |
| 4 | Summary interval | **5 minutes** (300s) |
| 5 | Submission format | **Video + writeup** — 30s LLM latency acceptable; can show pre-generated summaries in video |
| 6 | Sensor logging | Read frequently for live UI; **log periodically or on significant change** |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PERCEPTION + SENSORS (always running)                                   │
│                                                                          │
│  perception_loop ──► detection_enter / detection_exit / sound  ──► DB   │
│  sensor_loop     ──► SensorCache (every 2s) ──► GET /api/sensors        │
│                    ──► sensor:* (periodic or delta)            ──► DB   │
│  rules engine    ──► action_executed (once)                    ──► DB   │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   ▼
                          events table (SQLite)
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         ▼                                                   ▼
  MemorySummarizer (every 5 min)                    POST /api/ask
         │                                                   │
         ▼                                                   ▼
  digest.py (deterministic)                      context.py (budget)
         │                                                   │
         ▼                                                   ▼
  LLM summarize_period() (optional)              LLM query_memory()
         │                                                   │
         ▼                                                   ▼
  summaries table                                JSON answer to dashboard
```

### Three compression layers

| Layer | Mechanism | Token budget role |
|-------|-----------|-------------------|
| Raw events | SQLite append-only | Last ~5 min only, high-signal topics |
| Digests | Pure Python aggregation | Input to LLM (~100–300 tokens per 5 min) |
| Narratives | LLM (or digest fallback) | Queried for older windows (~100 tokens each) |

At query time for "last hour": ~12 stored narratives + 1 raw digest tail ≈ **1,500 tokens** — fits 2048 context with room for prompt.

---

## 4. Event logging changes

### 4.1 Remove `perception` topic

Delete bundled snapshot logging in `perception_logger_factory`. The `perception` topic is removed entirely. No migration of old rows required (append-only history can coexist; digest ignores `perception` if present).

### 4.2 New perception event topics

Logged from `perception_loop` in `main.py` when labels change or sounds fire:

| Topic | When | Payload |
|-------|------|---------|
| `detection_enter` | Label appears in frame (not in previous tick) | `{"label": str, "confidence": float}` |
| `detection_exit` | Label disappears from frame | `{"label": str}` |
| `sound` | New sound in merged snapshot (dedupe per 2s cooldown) | `{"label": str, "confidence": float}` |

**Sound deduplication:** Track `_last_sound_log: dict[str, float]` (label → timestamp). Only log if same label not logged within `SOUND_LOG_COOLDOWN` (2.0s, matches mic cooldown).

**Confidence on enter:** Use max confidence from current detections for that label.

### 4.3 Fix duplicate `action_executed`

Remove `db.log("action_executed", ...)` from `rules/engine.py::_execute`. Keep logging only in `action_handler_factory` in `main.py` (runs after action execution, single source of truth).

### 4.4 Sensor read vs sensor log (split)

**Problem today:** `sensor_loop` reads and logs at 0.5s → 28,800 rows/hour/sensor. Charts work but memory pipeline drowns in noise.

**New behavior:**

| Path | Interval | Purpose |
|------|----------|---------|
| MCU read + `SensorCache` update | **2.0s** (`sensor_read_interval`) | Live dashboard, rules engine sensor triggers |
| SQLite `sensor:{name}` log | **30s** OR **on delta** | Timeseries charts, memory digests |

**Change thresholds** (log immediately if exceeded since last logged value):

| Sensor key | Threshold |
|------------|-----------|
| `temperature_c` | ±0.5 °C |
| `distance_cm` | ±5 cm |
| `movement_intensity` | ±0.1 |
| `accel_x`, `accel_y`, `accel_z` | ±0.2 g |

**Implementation:** `sensor_loop` maintains `_last_logged: dict[str, tuple[float, float]]` mapping sensor → `(value, timestamp)`.

```python
def _should_log_sensor(name: str, value: float, now: float) -> bool:
    last_val, last_ts = _last_logged.get(name, (value, 0.0))
    if now - last_ts >= settings.sensor_log_interval:
        return True
    threshold = SENSOR_THRESHOLDS.get(name, 0.0)
    return abs(value - last_val) >= threshold
```

### 4.5 New live sensor endpoint

`GET /api/sensors` — returns current `SensorCache.readings` plus timestamp:

```json
{
  "timestamp": 1721361600.5,
  "readings": {
    "temperature_c": 22.4,
    "distance_cm": 87.2,
    "movement_intensity": 0.03,
    "accel_x": 0.01,
    "accel_y": -0.02,
    "accel_z": 1.01
  }
}
```

Dashboard charts poll this every **2s** for a live numeric readout (optional: small "current value" label above each chart). Timeseries charts continue using `/api/timeseries` (coarser DB data).

### 4.6 Fix timeseries topic list

In `GET /api/timeseries/all`, replace:

```python
topics = ["detection", "sound", "action_executed"]
```

with:

```python
topics = ["detection_enter", "sound", "action_executed"]
```

`detection_enter` events have `data.label` but not `data.value`. Extend `EventDB.timeseries` OR add a dedicated count-based timeseries for discrete events (see §5.2).

### 4.7 Complete event topic registry

| Topic | Logged by | In digest? |
|-------|-----------|------------|
| `detection_enter` | perception_loop | Yes — `detections_entered` |
| `detection_exit` | perception_loop | Yes — `detections_exited` |
| `sound` | perception_loop | Yes — `sounds` |
| `sensor:*` | sensor_loop (throttled) | Yes — aggregates only |
| `action_executed` | action handler | Yes — `actions` |
| `rule_created` | `/api/command` | Yes — `rules_created` |
| `memory_query` | `/api/ask` | No (meta) |
| `summary_created` | summarizer | No (meta; shown in activity) |

---

## 5. Memory layer

### 5.1 `summaries` table

Added to `aware.db` (same file as `events` and `rules`):

```sql
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    digest TEXT NOT NULL,        -- JSON: PeriodDigest serialized
    narrative TEXT NOT NULL,     -- LLM output OR digest_to_text() fallback
    event_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summaries_period_end ON summaries (period_end);
```

### 5.2 `EventDB` new methods

| Method | Signature | Behavior |
|--------|-----------|----------|
| `query_range` | `(start: float, end: float, topics: list[str] \| None = None, limit: int = 2000) -> list[dict]` | `WHERE timestamp >= start AND timestamp < end`, optional topic filter, ASC order |
| `query_since` | `(since: float, **kwargs) -> list[dict]` | Convenience: `query_range(since, time.time())` |
| `count_range` | `(start: float, end: float, topic: str \| None = None) -> int` | Count for summarizer skip logic |
| `last_summary_end` | `() -> float \| None` | `SELECT MAX(period_end) FROM summaries` |
| `store_summary` | `(period_start, period_end, digest, narrative, event_count) -> int` | Insert, return id |
| `get_summaries` | `(since: float, until: float \| None = None, limit: int = 50) -> list[dict]` | For context builder + dashboard |
| `event_counts` | `(start, end) -> dict[str, int]` | Per-topic counts for digest (optional helper) |

**Discrete event timeseries:** Add `event_count_timeseries(topic, window_seconds, bucket_seconds)` that counts rows per bucket (for `detection_enter` / `sound` charts). Reuses bucket SQL pattern from existing `timeseries` but `COUNT(*)` instead of `AVG(value)`.

### 5.3 `aware/app/memory/digest.py`

Pure functions, no I/O, fully unit-tested.

```python
@dataclass
class PeriodDigest:
    period_start: float
    period_end: float
    detections_entered: dict[str, int]
    detections_exited: dict[str, int]
    sounds: dict[str, int]
    actions: list[dict[str, object]]
    rules_created: list[str]
    sensors: dict[str, dict[str, float]]  # {name: {min, max, avg, first, last}}

def build_digest(events: list[dict[str, object]]) -> PeriodDigest: ...
def digest_to_text(digest: PeriodDigest) -> str: ...
def digest_to_json(digest: PeriodDigest) -> str: ...
```

**`digest_to_text` example output:**

```
11:15–11:20 | entered: person×1 | exited: person×1 | sounds: doorbell×1 | temp 22.1→23.3°C (+1.2) | distance 120→45cm | actions: greet_person spoke "welcome"
```

**Rules:**
- Deduplicate `action_executed` by `(rule, action, int(timestamp))` if duplicate rows exist from pre-fix data.
- Ignore legacy `perception` topic rows (or treat as presence counts for backward compat — optional, not required).
- Sensor aggregates: min/max/avg/first/last over all `sensor:*` rows in window.
- Empty window → return `None` from `build_digest`; summarizer skips.

### 5.4 `aware/app/memory/context.py`

```python
def parse_time_window(
    question: str,
    now: float,
    *,
    default_seconds: int = 3600,
) -> tuple[float, float]:
    """Regex-based. Returns (start, end) unix timestamps."""

def build_memory_context(
    *,
    question: str,
    window_start: float,
    window_end: float,
    summaries: list[dict[str, object]],
    events: list[dict[str, object]],
    max_chars: int = 6000,
) -> str:
    """Assemble context string for query_memory. Truncates oldest content first."""
```

**Time window patterns (deterministic, no ML):**

| Pattern | Window |
|---------|--------|
| `last (\d+) minutes?` | N × 60s |
| `last (\d+) hours?` | N × 3600s |
| `last hour` / `past hour` | 3600s |
| `today` | midnight local → now |
| `this morning` | 06:00 → 12:00 (or 06:00 → now if before noon) |
| `tonight` / `this evening` | 18:00 → now |
| `just now` / `recently` | 600s |
| (default) | `default_seconds` (3600) |

**Context assembly order (append in this order, truncate from top if over budget):**

1. Header: `Activity log from {start} to {end}.`
2. Stored summaries (narrative text, one line each, chronological)
3. Unsummarized tail: `digest_to_text(build_digest(tail_events))` for events after last summary
4. Notable raw events if budget remains: `action_executed`, `detection_enter`, `detection_exit` only — never raw `sensor:*` rows

---

## 6. Background summarizer

### 6.1 `aware/app/memory/summarizer.py`

```python
@dataclass
class SummaryResult:
    period_start: float
    period_end: float
    event_count: int
    narrative: str
    used_llm: bool

class MemorySummarizer:
    def __init__(
        self,
        db: EventDB,
        llm: LLMClient,
        interval_seconds: float = 300.0,
    ) -> None: ...

    async def run(self) -> None:
        """Infinite loop. sleep(interval). summarize_once(). Handles CancelledError."""

    async def summarize_once(self) -> SummaryResult | None:
        """Single period. Testable without loop."""
```

**`summarize_once` algorithm:**

1. `now = time.time()`
2. `last_end = await db.last_summary_end()` or `now - interval`
3. `period_end = now` (or align to floor: `now // interval * interval` — either is fine; use simple `now` for MVP)
4. If `period_end - last_end < interval * 0.9`: return `None` (not enough time elapsed)
5. `events = await db.query_range(last_end, period_end)`
6. If empty: return `None`
7. `digest = build_digest(events)`; if `None`: return `None`
8. `digest_text = digest_to_text(digest)`
9. Try `narrative = await llm.summarize_period(digest_text)` with 60s timeout
10. On any LLM failure: `narrative = digest_text`, `used_llm = False`
11. `await db.store_summary(last_end, period_end, digest_to_json(digest), narrative, len(events))`
12. `await db.log("summary_created", {"period_start": last_end, "period_end": period_end, "narrative": narrative[:500]})`
13. Return `SummaryResult(...)`

### 6.2 Concurrency

`asyncio.Lock` shared between summarizer and `/api/ask` — only one LLM call at a time. If lock held, `/api/ask` waits (up to `llm_timeout`). Summarizer skips LLM call if lock not acquired within 5s (store digest-only narrative).

### 6.3 Lifespan wiring (`main.py`)

```python
llm_lock = asyncio.Lock()
summarizer = MemorySummarizer(db, llm, settings.memory_summary_interval)
if settings.memory_summary_enabled:
    summarizer_task = asyncio.create_task(summarizer.run())
# shutdown: summarizer_task.cancel()
```

---

## 7. LLM integration

### 7.1 New protocol method

Add to `LLMClient` protocol and both `StubLLM` / `LlamaLLM`:

```python
async def summarize_period(self, digest_text: str) -> str: ...
```

**Stub:** return `digest_text` unchanged.

**Llama (`/completion` API, consistent with `create_rule`):**

```
Summarize this activity log in 2-3 sentences. Include specific times and counts. Only state facts from the log.

Log:
{digest_text}

Summary:
```

Parameters: `temperature=0.2`, `n_predict=128`, no grammar constraint.

Record latency on `LLMStats`.

### 7.2 Improve `query_memory`

**Prompt (completion API):**

```
You are AWARE, an on-device space monitor. Answer the question using only the activity log below. Include specific times when available. If the log does not contain the answer, say so.

Activity log:
{context}

Question: {question}

Answer:
```

Parameters: `temperature=0.3`, `n_predict=256`.

Record stats (currently missing). Return `[error] ...` on failure (existing behavior).

### 7.3 Board LLM config (measured 2026-07-19)

SSH `arduino@10.255.228.240`:

| Metric | Value |
|--------|-------|
| Total RAM | 3.6 GiB |
| Available (idle + llama-server) | ~2.2 GiB |
| Current model | MiniCPM5-1B Q4_K_M, `-c 2048 --mlock` |
| llama-server idle RSS | ~4 MB (weights locked separately) |

**Recommendation for MVP:**

- Keep **Q4** — sufficient RAM headroom with YOLO + FastAPI + MJPEG.
- Keep **`-c 2048`** — hierarchical summaries make larger context unnecessary for MVP.
- Try **Q8** only after measuring `free -h` with full stack running (aware + YOLO + MJPEG + llama under load). Not a spec blocker.

`AWARE_LLM_CTX_SIZE` in config should be documented to match `scripts/llama-server.service` `-c` flag (currently unused — fix in implementation).

---

## 8. REST API

### 8.1 `POST /api/ask`

**Request:**

```json
{
  "question": "what happened in the last hour?",
  "since": null,
  "window": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `question` | string, required | Natural language question |
| `since` | float, optional | Unix timestamp override for window start |
| `window` | int, optional | Window length in seconds (used with `since` or as `now - window`) |

**Response:**

```json
{
  "answer": "Between 10:15 and 11:15, a person entered once...",
  "window_start": 1721358000.0,
  "window_end": 1721361600.0,
  "summaries_used": 11,
  "events_scanned": 47,
  "context_preview": "Activity log from...",
  "latency_ms": 28432.1,
  "used_llm": true
}
```

**Handler flow:**

1. Parse window from `question` / `since` / `window`
2. Fetch summaries + events
3. `context = build_memory_context(...)`
4. Acquire `llm_lock`
5. `answer = await llm.query_memory(question, context)`
6. `await db.log("memory_query", {...})`
7. Return response

### 8.2 `GET /api/summaries`

Query params: `limit` (default 20), `since` (optional float).

Returns list of `{id, period_start, period_end, narrative, event_count, created_at}` — digest omitted from list response (available via detail if needed later).

### 8.3 `GET /api/sensors`

Returns live `SensorCache` readings (§4.5).

### 8.4 `GET /log` alias (optional)

`GET /log?since=&topic=&limit=` → alias to `GET /events` with same params. Matches original design doc; low priority.

---

## 9. Dashboard changes

### 9.1 New Ask card

Insert below the **Command** card in `dashboard/index.html`:

```
┌─────────────────────────────────────────────────────────┐
│  ASK                                                     │
│  [ what happened in the last hour?          ] [ Ask ]    │
│  ✓ answer text here...                                   │
│  ▸ context preview (collapsible)                         │
│  Latest summary: "Between 11:10-11:15, person entered..." │
└─────────────────────────────────────────────────────────┘
```

**Behavior:**

- `POST /api/ask` on button click or Enter
- Button shows `...` while waiting (no timeout in UI — video can edit wait)
- Display `answer` on success; show `context_preview` in collapsible `<details>`
- Poll `GET /api/summaries?limit=1` every 30s for "Latest summary" footer
- On error: show `✗` + error message

**Styling:** Reuse `.command-form` / `.command-input` / `.command-btn` classes. Ask button uses `#00bbff` accent to distinguish from Teach green.

### 9.2 Sensor live values

Above each sensor chart, show current reading from `GET /api/sensors` polled every 2s:

```html
<span id="tempLive" style="color:#ff4444;font-size:18px">--</span> °C
```

Charts continue using `/api/timeseries` (DB-backed, coarser).

---

## 10. Configuration

New settings in `config.py` / `.env.example`:

| Env var | Default | Description |
|---------|---------|-------------|
| `AWARE_SENSOR_READ_INTERVAL` | `2.0` | Seconds between MCU reads + cache update |
| `AWARE_SENSOR_LOG_INTERVAL` | `30.0` | Max seconds between DB logs per sensor |
| `AWARE_MEMORY_SUMMARY_INTERVAL` | `300` | Summarizer period (seconds) |
| `AWARE_MEMORY_SUMMARY_ENABLED` | `true` | Toggle background summarizer |
| `AWARE_MEMORY_CONTEXT_MAX_CHARS` | `6000` | Context string budget (~1500 tokens) |
| `AWARE_MEMORY_DEFAULT_WINDOW` | `3600` | Default ask window when no time in question |
| `AWARE_LLM_CTX_SIZE` | `2048` | Document only; must match llama-server `-c` |

---

## 11. Testing strategy

| Module | Test file | Key cases |
|--------|-----------|-----------|
| `digest.py` | `tests/test_digest.py` | Mixed events, sensor aggregates, action dedup, empty window |
| `context.py` | `tests/test_context.py` | Time regex, budget truncation, summary+tail assembly |
| `summarizer.py` | `tests/test_summarizer.py` | `summarize_once` with stub LLM, skip empty, LLM failure → digest fallback |
| `db.py` | `tests/test_memory.py` | `query_range`, summaries CRUD, `last_summary_end` |
| `/api/ask` | `tests/test_ask.py` | httpx `AsyncClient` + FastAPI app, stub LLM, seeded events |
| Sensor throttle | `tests/test_sensors.py` | `_should_log_sensor` thresholds, periodic flush |

All tests run locally with mocks — no board, no LLM server.

---

## 12. Demo / submission notes

Judging is **video + writeup**, not live on-stage. Recommended video flow:

1. **Teach** — create rule via dashboard (can use stub LLM for speed)
2. **Trigger** — person walks in, device speaks
3. **Wait** — let summarizer run 1–2 cycles (can time-lapse in edit)
4. **Ask** — "what happened in the last 30 minutes?" → show answer card
5. **B-roll** — show `summaries` table or activity log with `summary_created` events
6. **Close** — "all on-device, no cloud"

Writeup should mention hierarchical compression (raw → digest → narrative) as the solution to 2048-token context limits on a 1B edge model.

---

## 13. Out of scope (this spec)

- NL → SQL query generation
- Event retention / pruning
- WebSocket push for summaries or sensors
- `GET /log` alias (unless trivial during implementation)
- Q8 model swap (board experiment, not spec requirement)
- Migrating old `perception` rows
- Telegram / LED actions (separate specs)

---

## 14. Files to create or modify

| Action | Path |
|--------|------|
| **Create** | `aware/app/memory/digest.py` |
| **Create** | `aware/app/memory/context.py` |
| **Create** | `aware/app/memory/summarizer.py` |
| **Modify** | `aware/app/memory/db.py` |
| **Modify** | `aware/app/main.py` |
| **Modify** | `aware/app/config.py` |
| **Modify** | `aware/app/llm/interface.py` |
| **Modify** | `aware/app/llm/llama.py` |
| **Modify** | `aware/app/llm/stub.py` |
| **Modify** | `aware/app/rules/engine.py` (remove duplicate log) |
| **Modify** | `dashboard/index.html` |
| **Modify** | `.env.example` |
| **Create** | `tests/test_digest.py` |
| **Create** | `tests/test_context.py` |
| **Create** | `tests/test_summarizer.py` |
| **Create** | `tests/test_ask.py` |
| **Create** | `tests/test_sensors.py` |
| **Modify** | `tests/test_memory.py` |
| **Modify** | `docs/hardware-profile.md` (sensor intervals, memory pipeline) |

---

## 15. Implementation plan

A separate bite-sized implementation plan will be written to:

`docs/superpowers/plans/2026-07-19-memory-narration.md`

after this spec is reviewed.
