# AWARE Dashboard Design Spec

## Overview

Single-page web dashboard served as static files by FastAPI. Vanilla HTML/CSS/JS with Chart.js for time graphs. WebSocket for real-time data. Mock login for security simulation.

## Pages

### 1. Login Screen (`login.html`)

- Simple form: username + password fields
- **Always succeeds** — no real auth, just simulates security flow
- Stores `loggedIn=true` in localStorage
- Redirects to dashboard on success
- Clean, dark-themed design matching AWARE aesthetic

### 2. Main Dashboard (`index.html`)

Accessed after login. If `localStorage.loggedIn` is not set, redirect to login.

#### Layout (CSS Grid)

```
┌─────────────────────────────────────────────────────────┐
│  AWARE                              [status] [logout]   │
├─────────────────────────────────────────────────────────┤
│  Command Input                                          │
├──────────────────────────┬──────────────────────────────┤
│  Camera Feed             │  Active Rules                │
├──────────────────────────┴──────────────────────────────┤
│  Time Graphs (tabbed)                                    │
├─────────────────────────────────────────────────────────┤
│  Live Event Feed                                         │
└─────────────────────────────────────────────────────────┘
```

#### Components

**Header**
- AWARE logo/title
- Connection status indicator (green dot when WebSocket connected)
- Logout button (clears localStorage, redirects to login)

**Command Input**
- Text input + "Teach" button
- Sends natural language command to `POST /api/command`
- Shows success/failure feedback
- Displays parsed rule after submission

**Camera Feed**
- `<img>` or `<canvas>` element
- Receives JPEG frames via WebSocket (`topic: camera`)
- Draws bounding boxes for detections overlay on canvas
- Falls back to "Camera unavailable" placeholder when no feed

**Active Rules List**
- Table: name, when, then, priority, status
- Populated from `GET /api/rules`
- Updates via WebSocket (`topic: rules`)
- Color-coded priority: high=red, normal=blue, low=gray

**Time Graphs (Tabbed)**
- 4 tabs: Sensors, Objects, Sounds, Rules
- Chart.js line charts via CDN: `https://cdn.jsdelivr.net/npm/chart.js`
- Each tab shows relevant data stream over time
- Rolling window: last 60 data points (configurable)
- Updates via WebSocket (`topic: graph`)

| Tab | X-axis | Y-axis | Lines |
|-----|--------|--------|-------|
| Sensors | Time | Value | motion, distance, temperature, light, vibration |
| Objects | Time | Confidence | person, cat, dog, package, car |
| Sounds | Time | Confidence | doorbell, knock, glass_break, voice |
| Rules | Time | Count | triggers per minute |

**Live Event Feed**
- Scrolling list of recent events
- Each event: timestamp, type badge, description
- Types: `detection`, `sound`, `rule`, `action`, `sensor`
- Color-coded by type
- Auto-scrolls to newest
- Max 100 visible, older events removed from DOM

## API

### REST Endpoints (FastAPI)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/command` | POST | Submit NL command, returns parsed rule |
| `/api/rules` | GET | List active rules |
| `/api/events` | GET | List recent events |
| `/api/sensors` | GET | Current sensor readings |
| `/health` | GET | Health check |

### WebSocket

- **URL:** `ws://host:port/ws`
- **Protocol:** JSON messages with `topic` field

**Server → Client messages:**

```json
{"topic": "camera", "data": "<base64 jpeg>"}
{"topic": "detection", "data": {"label": "person", "confidence": 0.95, "bbox": [x,y,w,h]}}
{"topic": "sound", "data": {"label": "doorbell", "confidence": 0.87}}
{"topic": "sensor", "data": {"name": "temperature_c", "value": 22.1, "timestamp": 1234567890}}
{"topic": "rule_triggered", "data": {"name": "greet_person", "actions": ["speak"]}}
{"topic": "action_executed", "data": {"rule": "greet_person", "action": "speak", "params": {"text": "Welcome!"}}}
{"topic": "graph", "data": {"sensors": {...}, "objects": {...}, "sounds": {...}, "rules": {...}}}
```

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Markup | Vanilla HTML | No build step per AGENTS.md |
| Styling | CSS Grid + custom properties | Dark theme, responsive |
| Charts | Chart.js (CDN) | No build step, lightweight |
| Real-time | WebSocket (native) | FastAPI built-in support |
| Auth | localStorage flag | Mock only, no real auth |

## File Structure

```
dashboard/
  index.html          # Main dashboard
  login.html          # Mock login page
  css/
    style.css         # Global styles, dark theme
  js/
    app.js            # Main app logic, WebSocket
    camera.js         # Camera feed + bbox overlay
    charts.js         # Chart.js setup + updates
    events.js         # Live event feed
    rules.js          # Rules list management
    auth.js           # Mock login/logout
```

## Visual Design

- Dark theme: `#0a0a0a` background, `#1a1a1a` cards
- Accent: `#00ff88` (green) for AWARE branding
- Text: `#e0e0e0` primary, `#888` secondary
- Font: system monospace for data, system sans for UI
- Status indicators: green=active, yellow=warning, red=error
- Rounded corners, subtle shadows

## Scope

### In Scope (MVP)
- Mock login
- Command input
- Active rules list
- Camera feed placeholder (with bbox overlay when board connected)
- 4 time graphs (Chart.js)
- Live event feed
- WebSocket real-time updates

### Out of Scope
- Real authentication
- User management
- Mobile responsive (desktop-first for hackathon)
- Historical data browsing
- Report generation
- Settings/config UI

## Data Flow

```
User types command
  → POST /api/command
  → StubLLM.create_rule()
  → Parser.compile()
  → RulesStore.add()
  → WebSocket broadcast: rules update

Perception tick (500ms)
  → MockCamera.snapshot() or YOLO/YAMNet
  → EventBus.publish("perception")
  → RulesEngine.evaluate()
  → If match: EventBus.publish("action")
  → WebSocket broadcast: detection, sound, sensor, rule_triggered, action_executed
  → Chart.js update

Camera frame
  → Capture frame
  → Encode JPEG
  → WebSocket broadcast: camera
  → Canvas draw + bbox overlay
```
