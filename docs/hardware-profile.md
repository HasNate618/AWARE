# Hardware Profile & Service Distribution

## Platform

| Component | Part | Cores | Clock | Role |
|---|---|---|---|---|
| MPU | QRB2210 (Dragonwing) | 4x Cortex-A53 | 1.8GHz | Linux, AI/ML, web server |
| GPU | Adreno 702 | 1 CU | 844MHz | OpenCL 3.0 via rusticl (unused) |
| MCU | STM32U585 | Cortex-M33 | 160MHz | Realtime sensors, actuators |
| RAM | LPDDR4 | — | — | 4GB (3.6GB usable) |
| Camera | USB2.0 PC Camera | — | — | `/dev/video0`, 640x480 |
| Mic | USB camera mic | — | — | 48kHz → 16kHz resample |
| Speaker | TWS Mini Speaker (BT) | — | — | BlueALSA A2DP, MAC `15:D2:D2:C5:6B:0C` |

## Pinout & Expansion

### UNO Q Header (discrete GPIO)

```
                              ┌──────────────────────┐
  GPIO_D0  (PB7 )   D0  ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D1   (PA15) GPIO_D1
  GPIO_D2  (PC13)   D2  ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D3   (PB13) GPIO_D3
  GPIO_D4  (PC1 )   D4  ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D5   (PB4 ) GPIO_D5 ~PWM
  GPIO_D6  (PB11)   D6  ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D7   (PB10) GPIO_D7
  GPIO_D8  (PB1 )   D8  ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D9   (PB15) GPIO_D9  ~PWM
  GPIO_D10 (PC7 )   D10 ◀─▶  │●  ●  ●  ●  ●  RST●  ●│  ◀─▶  D11  (PB0 ) GPIO_D11 ~PWM
  GPIO_D12 (PB9 )   D12 ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D13  (PA8 ) GPIO_D13
                    GND ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  AREF
                    D14 ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D15  (PA2 ) A0 ADC
  GPIO_A1  (PA3 )   D16 ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D17  (PC0 ) A1 ADC
  GPIO_A3  (PB14)   D18 ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D19  (PC2 ) A2 ADC
                    D20 ◀─▶  │●  ●  ●  ●  ●  ●  ●  ●│  ◀─▶  D21  (PC3 ) A3 ADC
                              └──────────────────────┘
```

- **PWM-capable**: D5, D9, D11 (marked ~ on silkscreen)
- **ADC**: A0-A3 (D15, D17, D19, D21)
- **I2C**: Wire1 on Qwiic connector (SDA=PB3, SCL=PB6) — already used by Modulinos
- **UART**: `/dev/ttyHS1` ↔ STM32U585 (used by arduino-router)

### Qwiic Connector (already populated)
```
3.3V  SDA  SCL  GND
●────●────●────●
```
Modulinos daisy-chained: Thermo (HS300x), Distance (VL53L4CD), Movement (LSM6DSOX), Pixels

### Discrete RGB LED wiring
Connect common-cathode RGB LED to STM32 GPIO:
```
R ──[220Ω]── D5  (PWM, PB4)   or any ~PWM pin
G ──[220Ω]── D9  (PWM, PB15)
B ──[220Ω]── D11 (PWM, PB0)
Cathode ── GND
```
Needs STM32 firmware exposing `set_led_pwm(r_pin, g_pin, b_pin, r, g, b)` RPC.

## Sensor Data (currently flowing)

| Sensor | Key | Source | Update rate | Range |
|---|---|---|---|---|
| Temperature | `temperature_c` | Modulino Thermo (HS300x) | 0.5Hz read / 30s log | -40..125°C |
| Distance | `distance_cm` | Modulino Distance (VL53L4CD) | 0.5Hz read / 30s log | 0..400cm |
| Accelerometer X | `accel_x` | Modulino Movement (LSM6DSOX) | 2Hz | ±2/4/8/16g |
| Accelerometer Y | `accel_y` | Modulino Movement (LSM6DSOX) | 2Hz | ±2/4/8/16g |
| Accelerometer Z | `accel_z` | Modulino Movement (LSM6DSOX) | 2Hz | ±2/4/8/16g |
| Movement intensity | `movement_intensity` | Computed from accel deltas | 2Hz | 0..1 |

All sensors currently use **mock fallback data** (STM32 bootloader firmware doesn't register RPC methods yet).

## Trigger conditions available in vocabulary

| Type | Examples | Backend |
|---|---|---|
| Detection | `person`, `cat`, `dog`, `car`, `bottle`, `laptop`, ... | YOLOv8n COCO |
| Sound | `doorbell`, `knock`, `glass_break`, `voice`, ... | Energy-only (generic "sound") |
| Time | `morning`, `night`, `after 10pm`, `before 6am` | System clock |
| Transition | `enters`, `leaves`, `arrives`, `exits` | Frame diff |
| Sensor | `within 1m`, `closer than 50cm`, `farther than 2m`, `near`, `far` | distance_cm |
| Sensor | `hot`, `warm`, `cold`, `chilly` | temperature_c |
| Sensor | `moving`, `motion`, `still` | movement_intensity |

## Action types available

| Keyword | Type | Implementation | Status |
|---|---|---|---|
| `say`, `speak`, `announce` | speak | espeak-ng → BlueALSA BT | ✅ |
| `notify`, `alert` | telegram | Backend-agnostic, default dashboard toast | 🏗️ planned |
| `flash [color]` | led_flash | Modulino Pixels (RPC) — needs STM32 firmware | 🏗️ blocked |
| `turn on/off [color]` | led_on/led_off | Modulino Pixels (RPC) — needs STM32 firmware | 🏗️ blocked |
| `sound alarm` | alarm | Planned: TTS + tone combo | ❌ |
| `record` | record | Planned: save MJPEG clip | ❌ |
| `log` | log | EventDB (always active) | ✅ |

All sensors read via arduino-router every **2s** into `SensorCache` (`GET /api/sensors`). SQLite logs on **30s** interval or when values change beyond threshold.

## Memory narration pipeline

```
perception_loop → detection_enter / detection_exit / sound → SQLite
sensor_loop     → sensor:* (throttled)                    → SQLite
MemorySummarizer (300s) → digest → LLM → summaries table
POST /api/ask   → context builder → LLM → natural language answer
```

Event topics: `detection_enter`, `detection_exit`, `sound`, `sensor:*`, `action_executed`, `rule_created`, `summary_created`, `memory_query`.

## Service → Hardware Distribution

### Current (all on MPU CPU)

```
QRB2210 Cortex-A53
├── [core 0-3] YOLOv8n ONNX (CPU EP, 320x320, 2Hz)
├── [core 0-3] Audio energy event detection (5Hz)
├── [core 0-3] FastAPI + MJPEG stream (10FPS)
├── [core 0-3] Rules engine (500ms tick)
├── [core 0-3] Sensor loop RPC (0.5Hz read, 30s log)
├── [core 0-3] SQLite event log + summaries
├── [core 0-3] Memory summarizer (300s)
└── [core 0-3] Sensor → snapshot merge

llama.cpp (separate process)
└── MiniCPM5-1B inference (~30s rule creation, ~90–130s memory query)

STM32U585
└── Sensor polling (temp, distance, accelerometer) — bootloader only
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
  read_temp()         → float °C
  read_distance()     → float mm (converted to cm ÷10)
  accel_x/y/z()       → float m/s²
  movement_intensity() → float 0-1
  set_led(i, r, g, b, brightness) → void
  play_tone(freq, duration_ms) → void
  set_relay(i, state) → void
  read_sensor(name)   → float (generic fallback)
```

Mock fallback (`_MockProvider`) returns jittered defaults when STM32
methods are not registered or connection fails.
