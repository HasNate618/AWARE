# AGENTS.md

This file guides agentic coding tools working in this repo.

## Repo quick facts
- Project: AWARE — Autonomous Witness And Response Engine
- Hardware: Arduino UNO Q (Qualcomm Dragonwing QRB2210 + STM32U585)
- Backend: Python 3.12+ (FastAPI + asyncio)
- Dashboard: Vanilla HTML/CSS/JS (served as static files, no build step)
- Linting: ruff (check + format)
- Type checking: mypy (strict mode, `py.typed`)
- Testing: pytest

## Development is via SSH
- The board IS the dev environment. SSH into the UNO Q and work directly in `~/aware/`.
- This repo (on local machine) is the canonical source for version control.
- **All coding, testing, and running happens ON the board via SSH.**
- **Do not run ML models locally.** ML deps (ultralytics, llama-cpp-python, etc.) exist only on the board.
- Local venv: for IDE autocomplete, linting, and type-checking only (install core deps, skip ML).

### SSH workflow
```bash
# Connect to the board
ssh aware@uno-q.local           # or IP

# On the board: code lives at ~/aware/
cd ~/aware
source .venv/bin/activate

# Run the app directly (for dev)
python -m aware.app.main

# Restart the systemd service (for daemon mode)
sudo systemctl restart aware.service

# View logs
journalctl -f -u aware.service

# Run tests
pytest tests/ -v
```

### Initial board provisioning (one-time)
```bash
# From local machine, bootstrap the repo onto the board:
ssh aware@uno-q.local "git clone <repo-url> ~/aware && cd ~/aware && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"

# Pair Bluetooth speaker (on board):
bluetoothctl pair <MAC> && bluetoothctl connect <MAC>

# Configure env vars:
cp .env.example .env   # edit camera device, serial port, Telegram token, etc.
```

Board-side systemd service (lives on the board at `/etc/systemd/system/aware.service`):
```
[Unit]
Description=AWARE
After=network.target

[Service]
Type=simple
User=aware
WorkingDirectory=/home/aware
ExecStart=/home/aware/.venv/bin/python -m aware.app.main
Restart=always

[Install]
WantedBy=multi-user.target
```

## Setup (local)
```bash
# Create venv (for IDE support, linting, testing)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Lint
ruff check aware/ tests/

# Type check
mypy aware/

# Run tests (models mocked)
pytest tests/ -v
```

## Setup (board)
```bash
# On the UNO Q, already provisioned:
# - Python 3.12+, Debian base
# - Camera module, BT paired, Modulinos attached
# - Systemd service configured
# Deploy from local:
./scripts/deploy.sh
./scripts/restart.sh
```

## Commands (build/lint/test)
- Lint: `ruff check aware/ tests/`
- Format: `ruff format aware/ tests/`
- Type check: `mypy aware/`
- Run all tests: `pytest tests/ -v`
- Run single test: `pytest tests/test_parser.py -v`
- Deploy: `./scripts/deploy.sh`
- Board logs: `./scripts/logs.sh`

## Project structure
```
aware/
  app/
    main.py            # FastAPI app entry, launches rules loop
    config.py           # Env-based configuration
    core/
      event_bus.py     # asyncio in-process pub/sub
      loop.py          # 500ms rules engine tick
    perception/
      interface.py     # PerceptionSource protocol
      mock_camera.py   # Fake detections for testing
      yolo.py          # YOLOv8-nano (real, board only)
      yamnet.py        # YAMNet sound events (real, board only)
    llm/
      interface.py     # LLMClient protocol
      stub.py          # Deterministic English -> create_rule
      llama.py         # llama-cpp-python client (board only)
    parser/
      nl_parser.py     # English when/then -> triggers + actions
      vocabulary.py    # Keyword/regex maps: objects, sounds, times, actions
    rules/
      engine.py        # Active rules vs perception evaluation
      store.py         # SQLite rules table
    memory/
      db.py            # SQLite event log
    action/
      speaker.py       # BT audio (paplay via subprocess)
      leds.py          # Modulino Pixels via MCU bus
      notify.py        # Telegram notification
    mcu/
      bus.py           # SensorBus/ActuatorBus protocol
      mock.py          # Simulated STM32 + Modulinos
      serial_mcu.py    # /dev/ttyACMx serial protocol (board only)
  dashboard/           # Static HTML/CSS/JS served by FastAPI
  scripts/
    deploy.sh
    restart.sh
    logs.sh
    test.sh
tests/
```

## Code style and conventions

### Imports
- Stdlib first, then third-party, then local modules.
- Use `import aware.` prefix for internal imports (editable install: `pip install -e .`).
- No `*` imports.

### Formatting
- 4-space indentation, 100 char line limit.
- Double quotes. Trailing commas in multi-line collections.
- Follow ruff defaults; no deviations without reason.

### Types
- All public functions and methods MUST have type annotations.
- Use `Protocol` for interfaces (e.g. `PerceptionSource`, `LLMClient`, `SensorBus`).
- Return types explicit — no implicit `None` returns.
- `py.typed` marker present in package root.

### Naming
- Files/modules: snake_case
- Classes/Protocols: PascalCase
- Functions/variables: snake_case
- Constants: UPPER_SNAKE

### Error handling
- Perception sources: wrap in try/except; emit "unavailable" status on failure so the rules loop degrades gracefully.
- Actions: log failures, never crash the loop.
- LLM calls: timeout at 10s, fallback to stub on error.
- Serial MCU: reconnect with backoff on disconnect.
- Use `logging` module (configured in `config.py`); no `print()`.

### Testing
- Tests live in `tests/` mirroring `aware/` structure.
- Unit tests: every module tested in isolation with its mock.
- Integration tests: rules engine + event bus + stub LLM + mock MCU pipeline.
- Board-only: no board-side automated tests in CI. Test board features manually via SSH.
- Use `pytest` fixtures for common setup (test app, mock bus, in-memory SQLite).

## Architecture invariants
- **The LLM calls ONE tool**: `create_rule(name, when, then, priority)`. Never generates system commands.
- **The NL-Parser is deterministic**: regex + vocabulary. No ML. Always returns the same output for the same input.
- **The rules engine runs every 500ms**: synchronous evaluation of active rules against latest perception data.
- **Perception sources publish to event_bus**: rules engine consumes from event_bus. No direct coupling.
- **Dashboard is read-only subscriber**: gets events from event_bus via WebSocket. Never sends commands (those go through REST endpoints -> LLM -> parser -> rules).

## Notes for agentic changes
- Respect the interface/protocol pattern. When adding a new perception source, implement `PerceptionSource`.
- When adding a new action type, add to both `vocabulary.py` actions map and the `action/` module.
- Keep the stub/mock implementations up to date with the real ones — they must match the interface.
- Do not introduce cloud dependencies. Everything runs on-device.
- Do not add build steps (bundlers, transpilers) to the dashboard. Keep it vanilla HTML/CSS/JS.
- Scaffold scripts: when adding a new script, make it executable (`chmod +x`).

## Session context (as of 2026-07-18)
This section captures where the project was left off. OpenCode should read this on start.

### Current state
- **Camera + YOLO detection**: Working. USB2.0 PC CAMERA at /dev/video0. YOLOv8n ONNX. Confidence threshold 0.75.
- **Mic + sound detection**: Working. USB camera mic via sounddevice (48kHz -> 16kHz resample). Energy spike detection (2x baseline), 2s cooldown. Reports generic "sound" label.
- **BT speaker**: Paired (TWS Mini Speaker, 15:D2:D2:C5:6B:0C). Connected but PipeWire's bluez5 SPA plugin not creating an audio sink. Built-in audio output works via aplay on hw:1,1.
- **Speak action**: Implemented in aware/app/action/speaker.py using espeak-ng + aplay. Wired into action handler in main.py (fires on action type "speak").
- **Rule creation**: Stub LLM parses "when X say Y" correctly. Triggers: detection, sound, time. AND semantics across types.
- **Dashboard**: Live MJPEG video, detection log with timestamps, rules, activity log, command input.
- **Systemd service**: aware.service installed, enabled, auto-restarts. Working directory /home/arduino/aware.
- **Real LLM**: llama.cpp server running on board at port 8080. Not yet wired (set AWARE_LLM_SERVER_URL in .env).

### Board details
- User: arduino, password: aware2026
- IP: 10.255.228.240 on cybernet hotspot (DHCP, may change)
- Project: /home/arduino/aware
- Venv: /home/arduino/aware/.venv
- Models: /home/arduino/aware/models/ (yolov8n.onnx, yamnet.onnx, yamnet_classes.csv)
- Service: sudo systemctl start/stop/restart aware.service
- Logs: sudo journalctl -u aware.service -n 50
- Deps: sounddevice, scipy, onnxruntime, opencv-python-headless, aiosqlite, python-dotenv, pydantic-settings
- espeak-ng installed for TTS

### What to do next
1. Wire real LLM (set AWARE_LLM_SERVER_URL=http://127.0.0.1:8080 in ~/aware/.env)
2. Fix PipeWire BT audio (bluez5 SPA plugin not creating sink for TWS Mini Speaker)
3. Test speak action end-to-end via rule trigger
4. Telegram notification action
5. LED control via STM32 MCU bus

### Recent commits
- 782d1a0 feat: speak action via espeak-ng + built-in audio
- e5d091b fix: energy event detection, stop false positives
- 3fa1e23 fix: smarter sound classification, stop false positives
- 035a89c misc fixes: YOLO label map, YAMNet energy detection, dashboard charts, speaker tweaks
- Full repo at https://github.com/HasNate618/AWARE
