# Hardware Profile & Service Distribution

## Platform

| Component | Part | Cores | Clock | Role |
|---|---|---|---|---|
| MPU | QRB2210 (Dragonwing) | 4x Cortex-A53 | 1.8GHz | Linux, AI/ML, web server |
| GPU | Adreno 702 | 1 CU | 844MHz | OpenCL 3.0 via rusticl (unused) |
| MCU | STM32U585 | Cortex-M33 | 160MHz | Realtime sensors, actuators |
| RAM | LPDDR4 | — | — | 4GB (3.6GB usable) |

## Current Utilization (board live, 22:00 UTC)

```
CPU load: 2.98/4.00 (75% utilized, 56% idle)
  AWARE main process (YOLO + audio + web + rules): 164% CPU
  llama.cpp server (MiniCPM5-1B Q4_K_M):            8.5% CPU (idle)
  arduino-router (STM32 bridge):                      0.2% CPU
GPU: 0% utilization (Adreno 702 available via OpenCL)
MCU: sensor polling at 2Hz via arduino-router msgpack RPC
```

Before fix (AWARE_UVICORN_RELOAD=true):
  CPU load: 3.80/4.00 (96% saturated), 1.9% idle
  AWARE reloader: 64% CPU (full core wasted on file watching)

## Service → Hardware Distribution

### Current (all on MPU CPU)

```
QRB2210 Cortex-A53
├── [core 0-3] YOLOv8n ONNX (CPU EP, 320x320, 2Hz)
├── [core 0-3] Audio FFT classification (5Hz)
├── [core 0-3] FastAPI + MJPEG stream (10FPS)
├── [core 0-3] Rules engine (500ms tick)
├── [core 0-3] Sensor loop RPC (2Hz)
└── [core 0-3] SQLite event log

llama.cpp (separate process, ~9%)
└── MiniCPM5-1B inference (~30s per command)

STM32U585
└── Sensor polling (temp, distance, accelerometer)
```

### Recommended

```
QRB2210 — GPU (Adreno 702 via rusticl OpenCL)
├── YOLOv8n inference (ONNX OpenCLExecutionProvider)
│   - FP16 support available
│   - Integer dot product for quantized ops
│   - Unified memory = zero-copy input
│   - Estimated: frees 50-80% CPU

QRB2210 — CPU cores (with affinity)
├── Core 0: YOLO preprocessing + postprocessing (NMS, box overlay)
│            MJPEG frame encoding
├── Core 1: Audio FFT classification (5Hz)
│            Sensor RPC loop (2Hz)
├── Core 2: FastAPI request handling
│            Dashboard static file serving
│            WebSocket (future)
├── Core 3: Rules engine (500ms tick)
│            SQLite event log writes
│            Action dispatch

llama.cpp server (isolated)
├── Core 2-3 (shared): MiniCPM5-1B inference
│            Only busy during NL commands (~30s bursts)

STM32U585 — Realtime MCU
├── Sensor polling (temp, distance, accelerometer) at 50Hz
│   → Aggregate → report deltas to MPU every 500ms
├── Threshold monitoring: fire events on temp > 40°C, distance < 5cm
│   → Push to MPU without polling
├── LED pattern engine: "flash green 3x" runs autonomously
│   → Single RPC "animate(pattern_id)" vs per-frame control
├── Tone/buzzer: pre-loaded melodies triggered by ID
└── Health heartbeat: report alive + sensor summary every 1s
```

## Key Bottlenecks

| Issue | Status | Impact | Fix |
|---|---|---|---|
| uvicorn reloader | ✅ Fixed | Freed 64% CPU | `AWARE_UVICORN_RELOAD=false` |
| YOLO on CPU | Open | ~70-80% CPU | ONNX OpenCL EP → Adreno 702 |
| MJPEG at 10FPS | Open | ~40-50% CPU | Reduce to 5FPS, or GPU encode |
| llama.cpp isolation | ✅ Done | Independent process | systemd service

## OpenCL GPU Details

```
Platform: rusticl (Mesa OpenCL for Adreno)
Device:   FD702 (Adreno 702)
Version:  OpenCL 3.0 (EMBEDDED_PROFILE)
Clock:    844 MHz
Compute:  1 CU (max work group 1024)
Memory:   Unified with host (zero-copy)
Features: FP16, integer dot product, SVM
Driver:   Mesa 25.2.6 (msm DRM kernel driver)
```

ONNX Runtime supports `OpenCLExecutionProvider`. The integer dot product
extension is particularly useful for quantized YOLOv8n inference, and
unified memory eliminates input transfer overhead.

## MCU Protocol (arduino-router)

```
MPU ←→ Unix socket (/var/run/arduino-router.sock) ←→ STM32U585 via /dev/ttyHS1
Protocol: msgpack RPC (length-prefixed arrays)

Methods:
  read_temp()       → float °C
  read_distance()   → float mm (converted to cm ÷10)
  accel_x/y/z()     → float m/s²
  movement_intensity() → float 0-1
  set_led(i, r, g, b, brightness) → void
  play_tone(freq, duration_ms) → void
  set_relay(i, state) → void
  read_sensor(name) → float (generic fallback)
```

Mock fallback (`_MockProvider`) returns jittered defaults when STM32
methods are not registered or connection fails.

## Qualcomm Track Alignment

### 1. DragonWing CPU (MPU)
The QRB2210 runs all AI/ML inference, the web server, and the rules engine.
No cloud services. The quad Cortex-A53 handles YOLO object detection (ONNX Runtime),
MiniCPM5-1B LLM inference (llama.cpp server), audio classification (NumPy FFT),
and the FastAPI dashboard — all simultaneously on-device.

### 2. DragonWing GPU (Adreno 702)
The Adreno 702 is detected via rusticl OpenCL 3.0. Currently unused.
ONNX Runtime supports OpenCLExecutionProvider — YOLO inference could be
offloaded to the GPU (FP16 + integer dot product support, unified memory).
This is future work; the current CPU-only implementation is functional.

### 3. On-device AI
Three AI models run locally with zero cloud dependency:
- YOLOv8n (ONNX, 3.2M params) — real-time object detection at 2Hz
- MiniCPM5-1B (GGUF Q4_K_M) — natural language rule generation via llama.cpp
- Custom audio classifier — FFT-based sound event detection (doorbell, glass break, speech)
All models are quantized for edge deployment on 4GB RAM.

### 4. MCU, Realtime
The STM32U585 reads Modulino sensors (temperature, distance, accelerometer)
at 2Hz via arduino-router msgpack RPC over Unix socket. The MCU protocol
supports LED control, tone generation, and relay switching — enabling
actuator actions without MPU involvement. The `arduino-router` daemon
bridges the STM32 UART (/dev/ttyHS1) to the MPU via a local socket.

### 5. Specialty
AWARE is an autonomous agent that perceives its environment through camera,
microphone, and physical sensors, reasons about events using an on-device LLM,
and acts through speech, LEDs, and notifications. Users create automations
by typing natural language commands like "when person enters say welcome" —
the LLM parses intent, the deterministic NL parser compiles triggers and actions,
and the rules engine executes them at 500ms intervals. The modular protocol
architecture (PerceptionSource, SensorBus, ActuatorBus) makes it extensible
to new hardware without code changes.

### 6. Edge-only Value
The entire pipeline runs on-device. No internet required. No API keys.
No data leaves the board. Real-time response (sub-second for sensor triggers,
~30s for LLM commands). Works offline indefinitely. Privacy by design.
