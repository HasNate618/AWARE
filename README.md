# A.W.A.R.E. — Autonomous Witness And Response Engine

An autonomous edge AI agent that perceives its environment through vision, sound, and physical sensors, reasons about events using a local language model, and acts through speech, LEDs, and notifications — entirely on-device, with zero cloud dependency.

AWARE runs on the **Arduino UNO Q** (Qualcomm Dragonwing QRB2210 + STM32U585), an edge SBC with 4GB RAM, quad Cortex-A53, Adreno 702 GPU, and a Cortex-M33 real-time coprocessor.

---

## Quick Start

```bash
# SSH into the board
ssh aware@uno-q.local

# Start the service
cd ~/aware
source .venv/bin/activate
python -m aware.app.main

# Or restart the systemd service
sudo systemctl restart aware.service

# Dashboard at http://<board-ip>:8000
```

---

## What It Does

AWARE combines multiple AI models, sensor fusion, and natural language understanding into a single autonomous loop:

```
┌─────────────────────────────────────────────────────────────┐
│                    AWARE Pipeline                           │
│                                                             │
│  Camera ──→ YOLO (vision)  ──┐                              │
│  Mic    ──→ Audio (sound)  ──┼──→ Rules Engine ──→ Actions  │
│  Sensors──→ STM32 (temp/d) ──┘     (500ms)       │         │
│                                                  ↓         │
│                                          ┌──────────────┐  │
│                                          │ LLM (MiniCPM) │  │
│                                          │ NL → Rules    │  │
│                                          └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Users type natural language commands** into the dashboard. The LLM parses intent, the NL compiler generates deterministic triggers and actions, and the rules engine executes them every 500ms.

---

## Examples

### 1. Greet on Entry

**Command:** `when person detected say welcome`

**What happens:**
- Camera detects a person entering the frame
- Rule engine matches the "enter" transition
- Bluetooth speaker says "Welcome"

### 2. Farewell on Exit

**Command:** `when person leaves say goodbye`

**What happens:**
- Camera detects a person leaving the frame
- Rule engine matches the "exit" transition
- Bluetooth speaker says "Goodbye"

### 3. Custom Humor

**Command:** `when bottle detected say I'm hydrophobic`

**What happens:**
- LLM parses the command into a structured rule
- Camera detects a water bottle
- Bluetooth speaker says "I'm hydrophobic"

### 4. Multi-Condition Rule

**Command:** `when glass breaks after 10pm sound alarm`

**What happens:**
- Audio classifier detects glass break sound
- Time rule checks it's after 10pm
- Both conditions must be true (AND semantics)
- Alarm tone plays via MCU buzzer

### 5. Visual Notification

**Command:** `when doorbell rings flash green`

**What happens:**
- Audio classifier detects doorbell sound
- LED matrix flashes green via Modulino
- (Requires Modulino LED hardware connected to STM32)

### 6. Remote Notification

**Command:** `when person detected send telegram alert`

**What happens:**
- Camera detects a person
- Telegram message sent via Bot API
- Requires `AWARE_TELEGRAM_TOKEN` in `.env`

---

## Dashboard

The web dashboard (served at `:8000`) provides:

- **Live MJPEG video stream** with YOLO bounding boxes overlaid
- **Object detection log** with timestamps and confidence bars
- **Sound detection log** with classified audio events
- **Temperature and distance charts** with configurable time windows
- **Active workflows** — see and delete running rules
- **Command input** — type natural language to create new automations
- **Activity log** — full event history with rule triggers and actions
- **Login screen** with A.W.A.R.E. acronym reveal

---

## Hardware

### Arduino UNO Q (QRB2210 + STM32U585)

| Component | Part | Role |
|---|---|---|
| **MPU** | QRB2210 (4x Cortex-A53 @ 1.8GHz) | Linux, AI/ML, web server |
| **GPU** | Adreno 702 (844MHz, OpenCL 3.0) | Available for future GPU inference |
| **MCU** | STM32U585 (Cortex-M33 @ 160MHz) | Real-time sensors, actuators |
| **RAM** | 4GB LPDDR4 | All models + services run here |

### Peripherals

- **Camera:** USB2.0 PC CAMERA (320x240, MJPEG)
- **Microphone:** USB camera mic (48kHz → 16kHz resample)
- **Bluetooth Speaker:** TWS Mini Speaker (A2DP via BlueALSA)
- **Sensors:** Modulino Temperature + Distance (via STM32)
- **LEDs:** Modulino Pixels (via STM32)

---

## AI Models

| Model | Size | Purpose | Runtime |
|---|---|---|---|
| YOLOv8n | 13MB (3.2M params) | Object detection (2Hz) | ONNX Runtime (CPU) |
| MiniCPM5-1B Q4_K_M | 657MB | NL rule generation | llama.cpp server |
| Custom audio classifier | — | Sound event detection | NumPy FFT (CPU) |

All models run **100% on-device**. No API calls. No cloud. Works offline.

---

## Architecture

### Perception Layer

- **YOLO Camera** (`perception/yolo.py`): Captures frames at 320x240, runs YOLOv8n ONNX inference, returns labeled bounding boxes. Maps COCO classes to AWARE vocabulary (person, cat, dog, car, bottle, etc.)

- **Audio Classifier** (`perception/yamnet.py`): Captures audio from USB mic at 48kHz, resamples to 16kHz, classifies sound events via FFT spectral analysis (doorbell, glass break, speech, alarm). Uses energy spike detection with adaptive baseline.

- **MCU Sensors** (`mcu/serial_mcu.py`): Reads temperature, distance, and accelerometer from Modulinos via arduino-router msgpack RPC. Falls back to mock data when STM32 isn't connected.

### Reasoning Layer

- **LLM** (`llm/llama.py`): MiniCPM5-1B running on llama.cpp server (port 8080). Takes natural language commands, outputs structured JSON rules with grammar-constrained decoding (guarantees valid JSON output). Few-shot prompting with enter/exit transition examples.

- **NL Parser** (`parser/nl_parser.py`): Deterministic regex + vocabulary parser. Compiles LLM output into triggers (detection, sound, time, transition) and actions (speak, LED, telegram, alarm). Handles enter/exit transitions, AND semantics across trigger types, and time-of-day constraints.

- **Rules Engine** (`rules/engine.py`): Evaluates active rules against perception snapshots every 500ms. Supports AND semantics (all triggers must match), transition-aware matching (enter/exit), and 5-second cooldown to prevent spam.

### Action Layer

- **Speaker** (`action/speaker.py`): TTS via espeak-ng, played through BlueALSA Bluetooth speaker. 3-second debounce. Strips action verb prefixes from text.

- **LED** (via MCU): Flash, solid on, off via `set_led()` RPC call to STM32. Supports RGB colors.

- **Telegram** (planned): HTTP POST to Telegram Bot API for remote notifications.

- **Alarm** (via MCU): Tone generation via `play_tone()` RPC call to STM32 buzzer.

### Storage

- **SQLite** (`memory/db.py`): Event log with WAL mode for concurrent reads. Timeseries aggregation queries for dashboard charts. Sensor readings logged at 2Hz.

- **Rules Store** (`rules/store.py`): Persistent rule storage. Auto-deduplication on name collisions. Migration support for schema changes.

### Communication

- **arduino-router**: Daemon bridging MPU (Unix socket) to STM32 (UART `/dev/ttyHS1`). Uses msgpack RPC protocol. Handles sensor reads, LED control, tone generation, and relay switching.

- **Event Bus** (`core/event_bus.py`): In-process pub/sub for perception, action, and rules events. Decouples perception sources from rules engine.

---

## Technical Decisions

### Why YOLOv8n ONNX (not YOLOv5s, YOLOv8s, or EfficientDet)?

YOLOv8n is the smallest YOLO variant (3.2M parameters, 13MB ONNX). On a 4GB RAM device running an LLM, web server, and audio processing simultaneously, memory is the binding constraint. YOLOv8n provides 37.3 mAP@50-95 on COCO — sufficient for indoor object detection (person, cat, dog, bottle) while fitting in ~100MB RAM during inference. Larger models (YOLOv8s at 11M params) would consume 3-4x more memory with diminishing returns for our use case.

**ONNX Runtime** was chosen over TensorRT or TFLite because:
1. ONNX is framework-agnostic — the same model works on any platform
2. CPU EP on Cortex-A53 with ARM NEON is well-optimized in ONNX Runtime
3. No vendor lock-in to Qualcomm's SNPE/QNN SDK
4. Model export from Ultralytics is one command (`yolo export onnx`)

### Why llama.cpp (not vLLM, Ollama, or llamafile)?

llama.cpp is the only inference engine that:
1. Runs GGUF quantized models on ARM64 without GPU
2. Provides a stable HTTP API (compatible with OpenAI format)
3. Supports grammar-constrained decoding (JSON output guarantee)
4. Has mature `--mlock` support (prevents model from being swapped to disk)
5. Is available as a pre-built binary on the board

**Grammar-constrained JSON** is critical. Without it, LLMs frequently produce invalid JSON (broken quotes, extra fields, missing commas). The grammar forces output to exactly `{"name":"...", "when":"...", "then":"...", "priority":"..."}` — making the LLM reliable enough for production use.

### Why MiniCPM5-1B Q4_K_M (not Phi-3-mini, Qwen2-0.5B, or Gemma-2B)?

MiniCPM5-1B is one of the smallest instruction-tuned models that:
1. Fits in 1GB RAM (Q4_K_M quantization)
2. Follows structured output instructions reliably
3. Runs at ~30s per command on Cortex-A53
4. Has reasonable English comprehension for NL → structured rule parsing

Phi-3-mini (3.8B) and Gemma-2B are too large for 4GB RAM with other services running. Qwen2-0.5B is smaller but has weaker instruction following. MiniCPM5-1B is the sweet spot.

### Why SQLite (not PostgreSQL, Redis, or LevelDB)?

SQLite is the right choice for embedded edge devices:
1. Zero configuration — no daemon, no port, no credentials
2. Single file database — easy backup, easy reset
3. WAL mode handles concurrent reads without locking
4. ACID compliance prevents data corruption on power loss
5. `aiosqlite` provides async access without blocking the event loop

Redis would require a daemon. PostgreSQL would require 200MB+ RAM. LevelDB doesn't support SQL queries needed for timeseries aggregation.

### Why 500ms Rules Tick (not 100ms or 5000ms)?

The rules engine evaluates every 500ms (2Hz):
- **Fast enough** for human perception — a 500ms delay is imperceptible in most automation scenarios
- **Slow enough** to not waste CPU — at 100ms (10Hz), the rules engine would consume significant CPU for minimal benefit
- **Aligned with sensor update rate** — sensors report at 2Hz, so 500ms ensures no events are missed
- **Balanced with LLM latency** — LLM commands take ~30s; the rules tick is not the bottleneck

### Why BlueALSA (not PulseAudio or PipeWire)?

On headless embedded Linux:
1. BlueALSA is the lightest Bluetooth audio stack — no daemon overhead
2. PulseAudio adds ~30MB RAM and requires a running daemon
3. PipeWire is designed for desktop compositing, not embedded
4. `aplay -D bluealsa` is a single command — no routing configuration needed

### Why espeak-ng (not Piper, Coqui, or Google TTS)?

espeak-ng is:
1. Available by default on Debian — no installation needed
2. Pure CPU synthesis — no GPU or network required
3. Instant startup — no model loading delay
4. Adequate quality for short phrases ("welcome", "goodbye", "alert")

For a production deployment, Piper (local neural TTS) would be better. But for a demo, espeak-ng works and adds zero dependencies.

### Why Vanilla HTML/CSS/JS (not React, Vue, or Svelte)?

The dashboard has zero build steps:
1. No npm, no webpack, no bundler — instant deployment
2. Single `index.html` file — easy to edit and debug
3. Chart.js via CDN — no local build required
4. Works offline (after first load) — no npm cache needed
5. Fast cold start — no JavaScript hydration delay

For a demo, the build-step-free approach is ideal. For production, this could be migrated to a component framework.

### Why NOT Using the Adreno 702 GPU?

The Adreno 702 is available via rusticl OpenCL 3.0, and ONNX Runtime supports `OpenCLExecutionProvider`. However:

1. **1 compute unit** — the Adreno 702 in the QRB2210 has a single CU. For a 3.2M parameter model, the overhead of OpenCL kernel dispatch may negate any speedup over 4 Cortex-A53 cores.
2. **Unified memory** — while zero-copy is possible, the GPU driver adds latency for each inference call.
3. **Stability** — rusticl is a Mesa open-source driver, not Qualcomm's proprietary GPU driver. For a demo, CPU inference is more reliable.
4. **Future work** — GPU offloading is documented as a optimization path in `docs/hardware-profile.md`.

---

## Configuration

Environment variables (`.env` file):

```bash
# Camera
AWARE_CAMERA_DEVICE=/dev/video0

# MCU (STM32 via arduino-router)
AWARE_MCU_SERIAL_PORT=/dev/ttyHS1
AWARE_MCU_BAUD_RATE=115200

# LLM (llama.cpp server)
AWARE_LLM_SERVER_URL=http://127.0.0.1:8080
AWARE_LLM_TIMEOUT=90.0

# Telegram (optional)
AWARE_TELEGRAM_TOKEN=
AWARE_TELEGRAM_CHAT_ID=

# Database
AWARE_DB_PATH=aware.db

# Server
AWARE_HOST=0.0.0.0
AWARE_PORT=8000
AWARE_LOG_LEVEL=INFO

# Dev only (wastes ~64% CPU in production)
# AWARE_UVICORN_RELOAD=true
```

---

## Project Structure

```
aware/
  app/
    main.py            # FastAPI app entry, launches all loops
    config.py           # Env-based configuration
    core/
      event_bus.py     # asyncio in-process pub/sub
      loop.py          # 500ms rules engine tick
    perception/
      interface.py     # PerceptionSource protocol
      mock_camera.py   # Fake detections for testing
      yolo.py          # YOLOv8n ONNX (real, board only)
      yamnet.py        # Audio classification (real, board only)
    llm/
      interface.py     # LLMClient protocol
      stub.py          # Deterministic English → create_rule
      llama.py         # llama.cpp server client (board only)
    parser/
      nl_parser.py     # English when/then → triggers + actions
      vocabulary.py    # Keyword/regex maps: objects, sounds, actions
    rules/
      engine.py        # Active rules vs perception evaluation
      store.py         # SQLite rules table
    memory/
      db.py            # SQLite event log
    action/
      speaker.py       # BT audio (espeak-ng via BlueALSA)
    mcu/
      bus.py           # SensorBus/ActuatorBus protocol
      mock.py          # Simulated STM32 + Modulinos
      serial_mcu.py    # arduino-router msgpack RPC (board only)
  dashboard/
    index.html         # Static vanilla HTML/CSS/JS dashboard
  docs/
    hardware-profile.md # Hardware utilization analysis
  scripts/
    deploy.sh          # Deploy to board via SSH
    restart.sh         # Restart service
    logs.sh            # View service logs
    connect-bt.sh      # Bluetooth speaker auto-connect
tests/
```

---

## Development

```bash
# Local setup (for IDE, linting, testing only)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check aware/ tests/
ruff format aware/ tests/
mypy aware/
pytest tests/ -v

# Run on board
ssh aware@uno-q.local
cd ~/aware
source .venv/bin/activate
python -m aware.app.main
```

---

## License

MIT
