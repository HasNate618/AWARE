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
CPU load: 3.80/4.00 (96% saturated)
  AWARE main process (YOLO + audio + web + rules):  184% CPU
  uvicorn reloader (AWARE_UVICORN_RELOAD=1):         64% CPU
  llama.cpp server (MiniCPM5-1B Q4_K_M):              9% CPU (idle)
  arduino-router (STM32 bridge):                       0.2% CPU
GPU: 0% utilization
MCU: sensor polling at 2Hz via arduino-router msgpack RPC
```

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

| Issue | Impact | Fix |
|---|---|---|
| uvicorn reloader | -64% CPU (full core) | `AWARE_UVICORN_RELOAD=false` in systemd env |
| YOLO on CPU | ~70-80% CPU | ONNX OpenCL EP → Adreno 702 |
| MJPEG at 10FPS | ~40-50% CPU | Reduce to 5FPS, or offload encode to GPU |
| All services on 1 process | No isolation, one crash kills all | Run llama.cpp as dedicated systemd service (already done) |

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
