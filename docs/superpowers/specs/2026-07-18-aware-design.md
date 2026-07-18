# AWARE — Design Spec (MVP)

**Date:** 2026-07-18
**Target:** Hack The 6ix — Arduino UNO Q Qualcomm track
**Timebox:** ~36 hours of hacking

## 1. Overview

A single Python process running on the UNO Q (ARM64 Debian). FastAPI serves the dashboard and REST API. A background task runs the rules engine at 500ms intervals. The LLM (MiniCPM5-1B Q8) is called via a local llama.cpp server when the user types a command; on failure, it falls back to a deterministic stub. All perception models (YOLOv8, YAMNet) run on-device. The STM32 MCU is bridged over USB-CDC serial.

```
                        User types English
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  FastAPI routes                                              │
  │  POST /rule  ──► llm/stub ──► parser ──► rules/store         │
  │  GET  /log   ──► memory/db                                   │
  │  GET  /feed  ──► MJPEG from perception                       │
  │  WS   /ws    ◄── event_bus (live events → dashboard)          │
  └──────────────────────────────────────────────────────────────┘
                              │
  ┌──────────────────────────────────────────────────────────────┐
  │  Background loop (500ms tick)                                 │
  │  perception sources ──► event_bus ──► rules engine ──► actions │
  └──────────────────────────────────────────────────────────────┘
                              │
  ┌──────────────────────────────────────────────────────────────┐
  │  MCU bridge (async serial to STM32)                          │
  │  SensorBus ◄── Modulino readings                              │
  │  ActuatorBus ──► LED strips, relays, servos                   │
  └──────────────────────────────────────────────────────────────┘
```

## 2. Directory Layout

```
aware/
  py.typed
  __init__.py
  app/
    __init__.py
    main.py              # FastAPI app, background task startup
    config.py             # Env vars → typed config dataclass
  core/
    __init__.py
    event_bus.py          # asyncio pub/sub (typed events)
    loop.py               # 500ms rules evaluation tick
  perception/
    __init__.py
    interface.py           # PerceptionSource Protocol
    mock_camera.py         # Fake detections (always-available)
    yolo.py                # YOLOv8-nano (ultralytics, board only)
    yamnet.py              # YAMNet via tensorflow-hub (board only)
  llm/
    __init__.py
    interface.py           # LLMClient Protocol
    stub.py                # Deterministic pattern-match → create_rule
    llama.py               # llama-cpp-python client (board only)
  parser/
    __init__.py
    nl_parser.py           # when/then text → triggers + actions
    vocabulary.py           # Keyword + regex maps
  rules/
    __init__.py
    engine.py              # Active rule evaluation
    store.py               # SQLite CRUD
  memory/
    __init__.py
    db.py                  # SQLite event log (append-only)
  action/
    __init__.py
    speaker.py             # BT audio (paplay subprocess)
    leds.py                # Pulse width / NeoPixel via MCU
    notify.py              # Telegram Bot API
  mcu/
    __init__.py
    bus.py                 # SensorBus / ActuatorBus Protocols
    mock.py                # Simulated STM32 + Modulinos
    serial_mcu.py          # /dev/ttyACMx reader/writer
dashboard/                 # Served as static files by FastAPI
  index.html
  app.js                   # WebSocket client, rule form, event feed
  style.css
scripts/
  deploy.sh                # Git pull + pip install + restart
  restart.sh               # systemctl restart aware.service
  logs.sh                  # journalctl -f -u aware.service
  test.sh                  # ssh board "pytest tests/ -v"
tests/
  __init__.py
  conftest.py              # Fixtures: test app, mock bus, in-memory SQLite
  test_parser.py
  test_rules_engine.py
  test_event_bus.py
  test_llm_stub.py
  test_integration.py
requirements.txt           # Full deps (board)
requirements-dev.txt       # Lint/typecheck only (local)
.env.example               # Template for board .env
```

## 3. Interfaces (Protocols)

### 3a. PerceptionSource
```python
class PerceptionSource(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def latest(self) -> PerceptionFrame: ...
    def status(self) -> str: ...  # "ok", "unavailable", "degraded"
```

### 3b. LLMClient
```python
class LLMClient(Protocol):
    async def create_rule(
        self, user_text: str,
    ) -> CreateRuleResult: ...  # structured output
```

### 3c. SensorBus / ActuatorBus
```python
class SensorBus(Protocol):
    async def read_distance(self) -> float: ...
    async def read_temperature(self) -> float: ...
    async def read_motion(self) -> bool: ...
    async def read_vibration(self) -> float: ...

class ActuatorBus(Protocol):
    async def set_leds(self, pattern: str, color: str) -> None: ...
    async def set_relay(self, channel: int, state: bool) -> None: ...
    async def set_servo(self, channel: int, angle: float) -> None: ...
```

## 4. Event Bus

Typed events fire-and-forget with subscriber callback. In-process, no broker.

```python
@dataclass
class Event:
    source: str       # "yolo", "yamnet", "mcpu", "rules"
    kind: str         # "detection", "trigger", "action", "status"
    payload: dict[str, Any]
    timestamp: float

class EventBus:
    def publish(self, event: Event) -> None: ...
    def subscribe(self, callback: Callable[[Event], None]) -> None: ...
    async def async_publish(self, event: Event) -> None: ...
    async def async_subscribe(self, callback: Callable) -> None: ...
```

Both sync (rules loop) and async (FastAPI/WS) paths are supported. Async subscribers feed the WebSocket; sync subscribers are the rules engine and memory logger.

## 5. Rules Engine (core/loop.py)

Every 500ms:

1. Collect latest `PerceptionFrame` from each active source
2. Merge into a `WorldState` (dict of sensor readings + detections)
3. For each active rule in memory: evaluate `when` triggers against `WorldState`
4. If all triggers match → queue actions, log `"rule_triggered"`
5. Execute actions with a timeout (2s per action, skip on timeout)

```python
@dataclass
class Rule:
    id: str
    name: str
    triggers: list[Trigger]   # parsed from "when"
    actions: list[Action]     # parsed from "then"
    priority: str             # "high", "medium", "low"
    active: bool

class Trigger:                # Union type
    kind: str                 # "object", "sound", "time", "motion", "distance"
    value: str | float        # e.g. "person", "glass_break", 22.0
    operator: str             # "eq", "gt", "lt", "after", "before"

class Action:
    kind: str                 # "speak", "led", "notify", "relay"
    params: dict[str, Any]
```

Firing order: highest priority first, then insertion order.

## 6. NL-Parser (parser/)

This is the heart of the compiler. Takes plain English from the LLM's `create_rule` call and outputs structured triggers and actions. No ML. Deterministic.

### Vocabulary maps (vocabulary.py)

**Objects** (matches noun phrases):
```python
OBJECTS = {
    "person": ["person", "someone", "anyone", "people", "visitor", "human"],
    "dog": ["dog", "pet", "animal"],
    "package": ["package", "parcel", "box", "delivery"],
    "car": ["car", "vehicle", "truck"],
}
```

**Sounds** (matches auditory event names):
```python
SOUNDS = {
    "glass_break": ["glass break", "glass shattering", "breaking glass", "window break"],
    "doorbell": ["doorbell", "door bell", "ringing", "door bell rings"],
    "knock": ["knock", "knocking", "door knock", "someone knocking"],
    "voice": ["voice", "speech", "talking", "someone talking"],
    "alarm": ["alarm", "siren", "buzzer", "warning"],
    "silence": ["silent", "silence", "quiet", "nothing"],
}
```

**Times** (matches temporal expressions):
```python
# Parsed into: time_after(hour:24), time_before(hour:24), time_between(start, end)
TIME_PATTERNS = [
    (r"after (\d{1,2})\s*(pm|am|:00)?", "time_after"),
    (r"before (\d{1,2})\s*(pm|am|:00)?", "time_before"),
    (r"between (\d{1,2})\s*(?:and|to)\s*(\d{1,2})", "time_between"),
    (r"at night", "time_after(22:00)"),
    (r"in the morning", "time_between(6:00,12:00)"),
]
```

**Conditions** (matches comparisons):
```python
CONDITIONS = {
    "dark": ["dark", "night", "no light", "lights off", "dim"],
    "bright": ["bright", "daylight", "sunny", "lights on"],
    "hot": ["hot", "warm", "too hot"],
    "cold": ["cold", "freezing", "frost", "too cold"],
    "close": ["close", "near", "within"],
}
```

**Distance** (matches proximity expressions):
```python
DISTANCE_PATTERNS = [
    (r"within (\d+)\s*(meters?|m|feet?|ft)", "distance_lt"),
    (r"(?:farther|beyond) (\d+)\s*(meters?|m|feet?|ft)", "distance_gt"),
    (r"gets? (?:within|close)", "distance_lt(3)"),  # default 3m
]
```

**Actions** (matches action verbs):
```python
ACTIONS = {
    "speak": ["say", "speak", "greet", "welcome", "tell", "announce", "sound"],
    "led_flash": ["flash", "blink", "light up", "shine", "turn on lights"],
    "led_red": ["red", "flash red", "red lights"],
    "led_green": ["green", "flash green", "green lights"],
    "led_blue": ["blue", "flash blue", "blue lights"],
    "led_yellow": ["yellow", "flash yellow", "yellow lights"],
    "notify": ["notify", "alert", "send", "message", "telegram", "sms", "notify me"],
    "alarm": ["alarm", "siren", "sound the alarm", "trigger alarm"],
}
```

### Parser logic (nl_parser.py)

```python
def parse_when(when_text: str) -> list[Trigger]:
    triggers: list[Trigger] = []
    lowered = when_text.lower()
    # 1. Match objects → Trigger("object", name)
    # 2. Match sounds  → Trigger("sound", name)
    # 3. Match times   → Trigger("time", hour, operator)
    # 4. Match conditions → Trigger("condition", name)
    # 5. Match distance   → Trigger("distance", meters, operator)
    # 6. Return what matched + unmatched text as debug info
    return triggers

def parse_then(then_text: str) -> list[Action]:
    actions: list[Action] = []
    lowered = then_text.lower()
    # 1. Match action verbs → Action(kind, params)
    # 2. Handle conjunctions ("and", "then", comma) → split, recurse
    # 3. Return ordered list
    return actions
```

Punctuation is stripped. Extraneous text is logged at DEBUG level. If nothing matches, the rule is still stored but logs a warning — the LLM produced a `when`/`then` our vocabulary doesn't understand, which is a signal to expand it.

## 7. LLM Layer

### Types
```python
@dataclass
class CreateRuleResult:
    name: str
    when: str
    then: str
    priority: str  # "high", "medium", "low"

class LLMClient(Protocol):
    async def create_rule(self, user_text: str) -> CreateRuleResult: ...
    async def query_memory(self, question: str) -> str: ...
```

### Real client: llama.py
- Talks to a local [llama.cpp](https://github.com/ggerganov/llama.cpp) server via HTTP (port 8080)
- Model: MiniCPM5-1B Q8 GGUF (~1GB RAM)
- Uses structured output (grammar-constrained JSON) for `create_rule`
- Timeout: 10 seconds. On timeout or error → falls back to stub

### Cloud fallback (for testing acceleration)
- **NOT** the primary path — the point is edge AI, all on-device
- Valid for: rapid iteration during development, or as a last-resort fallback if MiniCPM5 Q8 won't run
- Implementation: a separate `llm/cloud.py` that calls a lightweight cloud model (e.g. OpenAI-compatible endpoint) via opt-in env var `AWARE_LLM_CLOUD_URL`
- Fallback chain: llama (primary) → cloud (if env var set, for dev/testing) → stub (always-available default)
- Enabled on the board for dev/testing only; never for the final demo unless the edge model fails entirely

### Stub: stub.py
Deterministic pattern-match for the demo scripts. Hardcoded responses for the pre-planned demo sentences. Any unknown input → reasonable defaults. This makes the entire pipeline testable without any LLM.

**The MiniCPM5 Q8 risk is the single highest project risk.** Mitigations:
1. Prove the GGUF loads on the UNO Q (night 1 priority)
2. If it doesn't fit in 4GB RAM → fall back to an even smaller model (e.g. TinyLlama 1.1B Q4, ~700MB)
3. If inference is too slow (>5s) → reduce context window or use prompt caching
4. If all else fails → stub is always available, the demo works end-to-end without LLM

## 8. Perception Layer

Two sources in MVP:

### YOLOv8-nano (perception/yolo.py)
- Runs ONNX or PyTorch on CPU (Adreno GPU optional, PyTorch might lack Vulkan/OpenCL backend)
- Produces: `[{label, confidence, bbox}]` on each frame
- Publishes `Event(kind="detection", payload={label, conf, bbox})`
- On error → sets status to "unavailable", rules engine skips object triggers

### YAMNet (perception/yamnet.py)
- TensorFlow Lite model via `tensorflow-hub` or `tflite-runtime`
- Audio input: default microphone capture via PyAudio
- Produces: top-5 sound labels with confidence every 1-2s
- Publishes `Event(kind="sound", payload={label, confidence})`

### Camera MJPEG stream
FastAPI route `GET /feed` streams JPEG frames from the camera device (`/dev/video0`). This is separate from YOLO — the camera capture loop writes to a shared buffer, and both the YOLO consumer AND the MJPEG route read from it. Implementation: a frame ring buffer of 1 (latest frame), thread-safe.

## 9. Action Layer

| Action | Implementation |
|--------|---------------|
| `speak(text)` | `paplay <wav>` or `espeak text` → BT speaker. Pre-generated WAVs for common phrases. |
| `led(pattern, color)` | ActuatorBus call → MCU over serial → Modulino Pixels (NeoPixel) |
| `notify(message)` | HTTP POST to Telegram Bot API (python-telegram-bot) |
| `relay(channel, state)` | ActuatorBus call → MCU GPIO |

Action execution is non-blocking (async tasks) with a 2-second timeout. Failures log at ERROR level but never raise into the rules loop.

## 10. MCU Bridge (mcu/serial_mcu.py)

STM32 exposes Modulinos over USB-CDC serial at `/dev/ttyACM0`. Protocol: newline-delimited JSON.

```json
→ {"cmd": "read", "sensor": "distance", "id": 1}
← {"ok": true,  "sensor": "distance", "value": 1.23, "id": 1}

→ {"cmd": "write", "actuator": "leds", "pattern": "flash", "color": "red", "id": 2}
← {"ok": true,  "id": 2}
```

Request IDs for correlation. On disconnect, exponential backoff reconnect (1s, 2s, 4s... cap 30s). SensorBus reads are cached at 100ms intervals to avoid flooding the serial bus.

Mock implementation (`mock.py`) implements the same Protocol with hardcoded/fake readings for full pipeline testing without hardware.

## 11. Memory Layer (memory/db.py)

Single SQLite database (`aware.db`) with one append-only table:

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL  -- JSON
);
```

REST endpoint `GET /log?since=&kind=` returns filtered JSON. The LLM's `query_memory` method composes SQL queries from NL questions.

## 12. Dashboard

Three sections:
1. **Live camera feed** — `<img>` pointed at `GET /feed` (MJPEG), auto-refreshes
2. **Rules** — List of active rules with enable/disable toggle (no edit). Form to type a new rule → POST /rule.
3. **Event log** — WebSocket feed (events appended in real time), filtered by type

All vanilla — no React, no build step. Served as static files by FastAPI (`StaticFiles` middleware).

## 13. Configuration (app/config.py)

```python
from dataclasses import dataclass
from os import environ

@dataclass
class Config:
    camera_device: str = environ.get("AWARE_CAMERA", "/dev/video0")
    serial_device: str = environ.get("AWARE_SERIAL", "/dev/ttyACM0")
    bt_speaker_mac: str = environ.get("AWARE_BT_MAC", "")
    telegram_token: str = environ.get("AWARE_TELEGRAM_TOKEN", "")
    llm_server_url: str = environ.get("AWARE_LLM_URL", "http://127.0.0.1:8080")
    llm_cloud_url: str = environ.get("AWARE_LLM_CLOUD_URL", "")
    db_path: str = environ.get("AWARE_DB", "aware.db")
    log_level: str = environ.get("AWARE_LOG_LEVEL", "INFO")
    host: str = environ.get("AWARE_HOST", "0.0.0.0")
    port: int = int(environ.get("AWARE_PORT", "8080"))
```

## 14. Error Isolation

Each module wraps its own failures:

- **Perception sources**: catch → set status "unavailable" → rules loop skips that source's triggers
- **LLM calls**: catch → fallback to stub → rule still gets created (maybe less precise, but the pipeline doesn't stall)
- **MCU serial**: catch → reconnect with backoff → sensor reads return cached last-known value → actuators log failure
- **Actions**: catch → log error → rules loop continues
- **Rules engine**: outer try/except → log full trace → next tick proceeds normally

## 15. Testing Strategy

| Layer | Tests |
|-------|-------|
| parser | 10-15 fixed command strings → expected triggers + actions |
| llm/stub | Each demo sentence → correct CreateRuleResult |
| rules engine | Scripted perception events → expected actions fire |
| event bus | Publish → subscriber received correct event |
| integration | Stub + parser + rules engine + mock MCU — full pipeline on a known command |
| Memory | Insert events → query returns filtered results |

All testable locally (no hardware needed). Models are never imported in tests.

## 16. Build Phases

### Phase 0 — Scaffolding (2-3 hours)
- Create Python package structure, py.typed, setup.cfg/pyproject.toml
- Install deps on the board: FastAPI, uvicorn, sqlite3 (stdlib), pyserial, requests
- Prove SSH development loop works: edit → run `python -m aware.app.main` → see "Hello" with actual log output
- Write `.env.example`, config.py, start main.py (just a health endpoint)
- Copy dashboard static files with a placeholder layout
- Prove WebSocket: connect dashboard to event bus, type a test event, see it appear live

### Phase 1 — Core Pipeline (4-5 hours)
- Implement EventBus
- Implement memory/db.py
- Implement NL-Parser + vocabulary.py (the full MVP vocabulary)
- Implement stub LLM + LLMClient interface
- Implement rules store (SQLite) + engine
- Implement mock perception source
- Wire: POST /rule → LLM → parser → store → engine
- Test: type "When someone walks in, say welcome" → rule appears → fires on mock event

### Phase 2 — Perception (3-4 hours)
- Install ultralytics, tensorflow-hub on the board
- Implement yolo.py (verify YOLOv8-nano loads, check RAM)
- Implement yamnet.py (verify audio capture works, test with known sounds)
- Wire to event bus
- Implement MJPEG streaming endpoint
- Test: physical person walks in front of camera → rule fires

### Phase 3 — Actions + MCU (3-4 hours)
- Implement mock MCU, test full action pipeline
- Implement serial_mcu.py
- Flash/test Modulino firmware on STM32
- Implement speaker.py (prove BT audio routing works)
- Implement leds.py (Modulino Pixels)
- Implement notify.py (Telegram)
- Test: rule trigger → speaker says thing, LEDs change

### Phase 4 — LLM (2-3 hours)
- Download/prove MiniCPM5 Q8 GGUF loads on the board
- Start llama.cpp server, test connectivity
- Implement llama.py client
- Fallback chain: llama → cloud (if enabled) → stub
- Test: type natural command → LLM calls create_rule with correct fields

### Phase 5 — Polish (2-3 hours)
- Finalize dashboard UI (live feed, rule list styled, event log)
- Tune vocabulary for demo sentences
- Test full demo story end-to-end (3 times)
- Write demo script for judging
- Prepare fallback demo plan (stub-only, no LLM)

## 17. MiniCPM5 Q8 — De-Risk Plan (highest priority)

```
Download the GGUF file (likely from HuggingFace).
Check: does llama.cpp compile and run on ARM64 Debian?
  → If compilation fails, try prebuilt ARM binary
  → If binary runs but crashes, try llama.cpp Python bindings
Check: does the model load into 4GB RAM?
  → Available RAM after system ~3.2GB
  → Model: ~1GB Q8, maybe ~700MB Q4
  → YOLO + YAMNet + app overhead: ~200MB
  → Total: ~1.5GB. Should fit.
Check: inference latency
  → Target: <3s for create_rule tool call
  → If >5s, try Q4 quantization or a smaller model (TinyLlama 1.1B Q4_K_M, ~700MB)
  → If >10s, the LLM demo is unworkable; use stub for demo, show LLM working async

If MiniCPM5 Q8 is a confirmed NO-GO by end of Phase 1:
  → TinyLlama as primary
  → Stub for demo reliability
  → Cloud API (never mentioned to judges) for speed

If MiniCPM5 Q8 WORKS:
  → Use stub during development for deterministic testing
  → Swap in llama.py for the demo
  → Show it processing a novel command (not pre-scripted) for extra WOW
```

## 18. Out of Scope (MVP)

- BlazeFace / face recognition (not in MVP)
- MediaPipe hand/pose (not in MVP)
- Depth-Anything (not in MVP)
- Whisper speech-to-text (not in MVP)
- Edge Impulse on MCU (defer; Modulinos give basic sensor readings over serial)
- Email/SMS notifications (Telegram only)
- Rule editing (create + remove/deactivate only)
- Multi-camera
- Video clip recording
- Person re-identification / tracking

## 19. What's Next

Immediate next actions after spec approval:

1. **Prove the board is ready** — SSH in, confirm Python 3.12+, USB camera working, `/dev/ttyACM0` exists, BT paired
2. **Prove MiniCPM5 Q8 on the board** — download GGUF, compile llama.cpp, run inference, measure latency. This gates everything.
3. **Create writing-plans skill document** — break the spec into concrete, ordered implementation tasks
4. **Begin Phase 0 scaffolding**
