# AWARE — Autonomous Witness And Response Engine

## What Is It

**A device that can automate anything.**

You put AWARE in any physical space — home, office, workshop, warehouse, silo. You tell it what to care about in plain English. It watches, listens, and senses. When your condition is met, it acts. It also remembers everything, so you can ask what happened later.

No code. No app. No cloud. One board.

---

## Why It Exists

Automating a physical space shouldn't require a computer science degree. Right now you need separate devices, separate apps, rigid if/then editors, and a cloud service that could go down or spy on you. AWARE replaces all of that. One device. Plain English. Everything stays in your space.

---

## What It Does

### Automate
You type what you want in English. AWARE compiles it into a rule and runs it autonomously:

- "When someone walks in, say welcome and flash green"
- "If glass breaks after 10pm, sound the alarm and send me a Telegram"
- "When the silo gets within 10 meters, alert me"
- "If it gets dark and someone's outside, turn on the porch light"

Rules activate immediately and run forever until removed.

### Remember
Every detection is logged — who, what, when. You can ask later:

- "What happened today?"
- "Did anything unusual happen this week?"
- "When does the mail usually arrive?"

The device answers from its own memory — no cloud, no footage review.

### How It Works (简要)

1. You type an instruction in English
2. A local LLM understands it and calls `create_rule()`
3. A deterministic NL-Parser compiles it into triggers + actions
4. The rules engine checks perception data against active rules every 500ms
5. When a rule matches, actions fire (speak, flash, notify, relay)
6. Everything is logged — the LLM can query it later

No cloud. No API calls. The LLM never generates complex system commands — it just calls one tool. The parser is deterministic. The rules engine is real-time.

---

## How It Works

### The NL-Parse Architecture

The LLM never generates complex system commands. It does one thing: **understands what you want and calls a single tool.**

```
User: "When glass breaks after 10pm, sound the alarm and notify me"

LLM output:
  create_rule(
    name = "night_glass_break",
    when = "glass breaking sound after 10pm",
    then = "sound alarm, flash red lights, send telegram",
    priority = "high"
  )

Backend NL-Parser (deterministic):
  "when" text → regex + vocabulary → triggers: [sound_glass_break, time_after_22:00]
  "then" text → regex + vocabulary → actions: [relay_alarm, led_flash_red, send_telegram]
  → Structured rule → stored in SQLite → activated

Rules Engine (runs every 500ms):
  Perception data → check against active rules → trigger matched → execute actions
  No LLM involved. Sub-second response.
```

The LLM is the natural language understanding layer. The NL-Parser is the deterministic compiler. The rules engine is the runtime. Each layer does what it's best at.

### The Perception Layer (Always Running)

| Sense | Model | What It Knows |
|---|---|---|
| **Vision** | YOLOv8-nano | Objects, people, scenes — what's in the room |
| **Face** | BlazeFace | Who is here — known faces get personalized responses |
| **Hands/Pose** | MediaPipe | What people are doing — gesturing, sitting, walking |
| **Depth** | MiDaS / Depth-Anything | Where things are in 3D space |
| **Sound** | YAMNet (521 classes) | What's happening audibly — doorbells, music, tools, speech, silence |
| **Sensors** | Edge Impulse (MCU) | Physical environment — temperature, vibration, motion, light |

### The Reasoning Layer (On Demand)

| Component | What It Does |
|---|---|
| **LLM** (MiniCPM5-1B, Q8 quantization) | Understands natural language instructions. Calls `create_rule` with plain English fields. Queries memory when asked questions. Explains reasoning. |
| **NL-Parser** (Python, deterministic) | Compiles LLM's plain English "when"/"then" fields into structured triggers and actions using regex + vocabulary matching. Zero ML, 100% reliable. |
| **Rules Engine** (Python, continuous) | Checks all active rules against incoming perception data every 500ms. Triggers actions when conditions match. No LLM involvement at runtime. |

### The Action Layer (On Trigger)

| Action | Medium | Latency |
|---|---|---|
| Speak to visitors | BT Speaker via Linux audio stack | <500ms |
| Flash lights / show icons | LEDs via MCU (PWM/NeoPixel) | <10ms |
| Move physical objects | Servos / relays via MCU | <50ms |
| Send you a notification | Telegram / SMS via MPU | <1s |
| Record a video clip | Camera → storage via MPU | <1s |
| Display information | Dashboard via WebSocket | instant |

### The Memory Layer (Always Running)

Every perception event is logged with timestamp, context, and confidence score. The LLM queries this log when asked questions, generating natural language summaries from structured data.

---

## The Dual-Brain Architecture

The device runs on two processors that serve fundamentally different purposes:

**The Microprocessor (Linux)** handles everything that requires *understanding*: running vision models, classifying sounds, reasoning with the LLM, serving the dashboard, maintaining the memory database. It thinks.

**The Microcontroller (Real-time)** handles everything that requires *speed*: reading sensors 1,000 times per second, driving speakers and servos with precise timing, executing safety cutoffs in microseconds, running anomaly detection. It reacts.

They communicate through a bridge — the MCU tells the MPU "something just happened" when it detects a significant event, and the MPU tells the MCU "do this" when it decides on an action. Neither could do the other's job.

---

## The ML Models

Eight models running across four processors. All on-device, zero cloud.

| Engine | Model | What It Does |
|---|---|---|
| GPU | YOLOv8-nano | Object detection — people, objects, scenes |
| GPU | BlazeFace | Face detection + recognition |
| GPU | MediaPipe Hands/Pose | Hand tracking, body pose |
| GPU | Depth-Anything-Small | 3D depth from single camera |
| DSP (always-on) | YAMNet | 521 sound event categories at <1mW |
| CPU | MiniCPM5-1B Q8 | LLM — NL understanding + memory queries |
| CPU | Whisper-tiny | Speech-to-text (on-demand) |
| MCU | Edge Impulse | Vibration anomaly detection (<1ms) |

---

## Why It Can Only Exist at the Edge

**Latency** — When someone walks up to your door, the system responds in under a second. Cloud round-trips add 200-500ms minimum. On-device, perception-to-action takes 10-50ms.

**Privacy** — This device watches your home, your family, your daily patterns. That data never leaves the board. No cloud storage, no third-party servers, no terms of service. Your space's memory stays in your space.

**Reliability** — Works during internet outages, network failures, and remote deployments. The intelligence lives in the physical space, not in a data center that could go down.

**Power** — The DSP runs always-on audio classification at microwatts. The MCU monitors sensors continuously without waking the main processor. The system can operate on minimal power for extended periods.

---

## What Makes It Different

| Existing Approach | What AWARE Does Differently |
|---|---|
| Security cameras | Record but don't understand or act |
| Smart home (Alexa/Routines) | Cloud-dependent, rigid rules, no scene understanding |
| IoT sensor dashboards | Show numbers but don't explain what they mean |
| Industrial monitoring | Narrow focus, no NL interface |
| Custom ML projects | Require coding, one-off builds |

AWARE fuses vision, audio, and sensor data. You teach it in English. It compiles, executes, and remembers. All on-device. No cloud.

---

## Use Cases

| Space | What AWARE Does |
|---|---|
| **Home** | Greet visitors, detect intruders, monitor packages, frost alerts, pet monitoring |
| **Workshop** | Machine vibration health, tool tracking, safety guard (distance alarm), air quality |
| **Office** | Meeting room occupancy, after-hours security, delivery logging |
| **Warehouse** | Inventory alerts, motion logging, break-in detection |
| **Agriculture** | Silo fill level, frost warning, irrigation logging, pest detection |
| **Retail** | Customer greeting, shelf monitoring, closing photo log |

---
## The Core Loop

```
SENSE → REMEMBER → REASON → ACT → REMEMBER

Perception models continuously observe the environment.
Every observation is logged to memory.
When active rules match current perception, actions execute.
The results are logged back to memory.
The LLM can query memory at any time to explain, summarize, or detect patterns.
```

---

## Interaction

**Input:** Type natural language commands into a web dashboard served from the board. Ask questions. Give instructions. The LLM processes your input and calls `create_rule` with your words. The NL-Parser compiles them into executable rules.

**Output:** The device acts in the physical world (speaks, lights up, moves, sends notifications) and updates the dashboard in real-time with what it sees, hears, and decides.

---

## The Hardware

Arduino UNO Q — $50 single board computer with two processors:

| Processor | Role | Models |
|---|---|---|
| Qualcomm Dragonwing QRB2210 (4× A53, Adreno GPU, Hexagon DSP, 4GB RAM) | Intelligence | Vision, audio, LLM, dashboard |
| STM32U585 (Cortex-M33, Zephyr RTOS) | Real-time | Sensors, actuators, anomaly detection |

Wi-Fi 5, Bluetooth 5.1, USB-C, camera connectors, Qwiic sensor interface, Arduino-compatible headers.

---

## The Pitch

Elevator (5 sec): **"A device that can automate anything."**

Hook (15 sec): "You put it in any space, teach it in English, and it watches, listens, and acts. No code, no cloud."

Demo (3 min): Teach a rule → device executes it → ask what happened → it tells you.

Close (30 sec): "One $50 board. Eight ML models. Everything runs on-device. Your space's data never leaves your space."

---

---

# Hackathon Build Plan — Hack The 6ix 2026

## Prize Track Target

**Primary: Qualcomm — Build at the Edge with Arduino UNO Q**
- Prize: Meta Ray-Ban AI glasses per team member
- Fit: 5/5 — project literally matches the track description word-for-word
- Track requirement: "Run AI/ML inference locally on the Linux side while the MCU handles real-time sensing and control — no cloud required"

**Secondary (if eligible):**
- Best Hardware Hack (Studio Speakers)
- QNX Best Use of QNX ($1,000 CAD) — only if using QNX RTOS instead of Zephyr

## Idea Review Scores

| Criterion | Score | Notes |
|---|---|---|
| Prize track fit | 5/5 | Perfect Qualcomm track alignment |
| Buildable in timebox | 3/5 | Modulinos cut hardware setup to near-zero. Software is the bottleneck. |
| Demo wow factor | 5/5 | Teach-it-in-English + instant-action is unforgettable |
| **Overall** | **PURSUE** | Win with tight MVP, not ambitious scope |

## MVP Scope (80% reduction from full vision)

### What We Build

| Layer | MVP Scope |
|---|---|
| **Perception** | YOLOv8-nano for person detection + YAMNet for 3-4 sounds (doorbell, knock, glass break, voice) |
| **NL-Loop** | LLM calls `create_rule` → parser compiles → rule activates |
| **Action** | BT Speaker greeting + LED color change + Telegram notification |
| **Memory** | SQLite log of events with timestamps |
| **Dashboard** | Minimal web UI: live camera feed + rule list + event log |

### Demo Story

1. "I teach AWARE a behavior in English" → type command in dashboard
2. "It compiles it" → show rule appearing in rule list
3. "It executes it" → trigger the condition, device responds
4. "I can ask it what happened" → query memory, get natural language answer

---

## Hardware Requirements

### Core Computing

| Component | Source | Notes |
|---|---|---|
| Arduino UNO Q | Qualcomm kit (provided) | 4GB variant, includes USB-C cable + USB Hub + power supply |
| USB Hub | Qualcomm kit (provided) | **Critical** — splits USB-C for camera + power |
| Modulino: Movement | Qualcomm kit (provided) | PIR motion/presence detection |
| Modulino: Distance | Qualcomm kit (provided) | Ultrasonic ranging |
| Modulino: Thermal | Qualcomm kit (provided) | Temperature sensing |
| Modulino: Buzzer | Modulino bucket (grab) | Backup audio output if BT fails |
| Modulino: Pixels | Modulino bucket (grab) | NeoPixel LED strip — visual feedback |
| Modulino: Button | Modulino bucket (grab) | Physical input — manual trigger/reset |

### Action (Bring Your Own)

| Component | Source | Notes |
|---|---|
| Bluetooth Speaker | **Personal** | Audio output via BT 5.1 — no wiring needed |

### Additional (Rent from Hackathon)

| Component | Source | Qty | Notes |
|---|---|---|---|
| SparkFun Inventor's Kit | Rent (3 avail) | 1 | LEDs, breadboard, wires, resistors |
| MPU6050 (Qwiic) | Rent (8 avail) | 1 | Vibration/acceleration — fills gap no Modulino covers |
| Display Module | Rent (1 avail) | 1 | Status display — only 1 available, reserve immediately |

### Audio Decision: Bluetooth Speaker

**Decision: Bluetooth Speaker** — chosen for simplicity and audio quality.

The UNO Q's I2S audio pins (JMISC GPIO_98-101) require device tree modifications that aren't documented yet. The UNO Media Carrier (official audio accessory) isn't in the hackathon inventory. Rather than spending 4-8 hours hacking device trees, we use BT audio.

| Factor | BT Speaker | MAX98357A (rejected) |
|---|---|---|
| Setup time | Pair once in Linux, done | Device tree mod + level shifter + wiring |
| Audio quality | Good (built-in amp + enclosure) | Tinny (3Ω beater) |
| Demo risk | Pairing could fail | Bulletproof once wired |
| Hackathon fit | ✅ Fast to implement | ❌ Too much config time |
| Latency | 50-200ms (acceptable) | Sub-50ms (overkill for demo) |

**Mitigation for BT pairing risk:** Pair the speaker during setup, keep it powered on throughout the event. Test audio before judging. Have a USB audio adapter as fallback.

### Audio path

```
UNO Q (Debian Linux) → BT 5.1 → Speaker
```

On the Linux side, `pactl` or `bluetoothctl` handles the connection. Once paired, audio output is routed via the standard PulseAudio/PipeWire stack. The LLM or rules engine triggers audio playback with a simple `aplay` or `paplay` command.

**Fallback:** If BT fails, plug in a USB audio adapter + 3.5mm speaker via USB-C hub. Keep one at the table.

### Hardware Rent Priority List

**From hackathon rentable hardware (bring your own USB camera + BT speaker):**

1. **SparkFun Inventor's Kit** ×1 — wires, breadboard, resistors, LEDs
2. **MPU6050 (Qwiic)** ×1 — vibration/acceleration sensing, fills gap no Modulino covers
3. **Display Module** ×1 — status display (only 1 available — reserve immediately!)

**No longer needed (covered by Qualcomm kit):**
~~USB Webcam~~ → bring your own
~~Microphone Module~~ → use USB mic or Modulino sensors
~~Sparkfun Sound Detector~~ → covered above
~~Magnetic Switch~~ → Modulino movement sensor covers presence
~~Mini Relay~~ → Modulino latch relay covers this
~~Grove Starter Kit~~ → Modulinos cover this

---

## Hackathon Timeline

| Time | Event |
|---|---|
| **Fri 9:30 PM** | Hacking begins — check in, reserve hardware |
| **Fri 11:00 PM** | Hardware checkout portal opens |
| **Sat 11:59 PM** | Initial Devpost submission (select tracks) |
| **Sun 9:30 AM** | Hacking ends — final submission |
| **Sun 10:30 AM** | Judging begins — in-person pitch |
| **Sun 1:30 PM** | Closing ceremony — return hardware |

### Pitch Format

- 1 min setup
- 5 min pitch + Q&A (recommend 3 min pitch, 2 min questions)
- 1 min feedback
- **No slides** — demo-focused presentation

### Judging Criteria

- **Technical Difficulty** — significant hurdles, unique solutions, minimal API reliance
- **Uniqueness** — creative, original, not commonly seen at hackathons
- **Design** — UX considered, intuitive interface, sophisticated HCI for hardware
- **Completeness** — polished, fully working, goals accomplished

---

## Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Scope explosion | 🔴 High | Strict MVP — 1 perception modality, 1 action type, 1 demo scenario |
| ML model integration time | 🔴 High | Get YOLOv8 + YAMNet running on UNO Q first night |
| NL-Parser edge cases | 🟡 Medium | Demo with pre-tested commands only — don't improvise |
| BT speaker pairing failure | 🟡 Medium | Pair early, test before judging, USB audio adapter as fallback |
| Display module only 1 avail | 🟡 Medium | Reserve immediately — fallback to dashboard-only |
| Hardware checkout portal delays | 🟢 Low | Queue early, have backup plan with personal hardware |
