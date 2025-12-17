# The Alarm Clock - AI Coding Agent Instructions

## Domain-Driven Design (DDD) Vision

**Long-term architectural goal:**
This project is transitioning from a monolithic, event-driven "God Class" architecture to a clean **Domain-Driven Design (DDD)** architecture.

**Key DDD Principles to Guide Development:**
- **Rich Domain Model:** Business logic must reside in `core/domain/`. Entities should encapsulate both data and behavior.
- **Bounded Contexts:** Clearly separate subdomains:
  - **Alarm Context:** Scheduling, triggering, and recurring rules.
  - **Audio Context:** Playback, volume, streams, and Spotify integration.
  - **Hardware Context:** Input handling (buttons, rotary) and sensors.
  - **UI Context:** Display rendering and menu navigation.
- **Ubiquitous Language:** Use consistent business terms (`AlarmDefinition`, `AudioStream`, `WakeUpSequence`).
- **Dependency Rule:** Domain layer must NOT depend on Infrastructure or Interface layers.

## Current Architecture Analysis & Pain Points (Refactoring Roadmap)

The codebase currently suffers from several architectural violations that must be addressed. When working on tasks, prioritize refactoring these areas:

### 1. The `Controls` God Class (Severity: High)
- **Problem:** `src/core/application/controls.py` is a massive service handling everything: scheduler, event subscriptions, weather, alarm logic, and volume. It couples all bounded contexts together.
- **Goal:** Decompose `Controls` into specific Application Services:
  - `AlarmService`: Orchestrates alarm scheduling and triggering.
  - `AudioService`: Handles volume and playback requests.
  - `SystemService`: Manages wifi, weather, and hardware events.

### 2. Anemic Domain Models (Severity: High)
- **Problem:** `src/core/domain/model.py` contains mostly `@dataclass` structures with little behavior. Logic that belongs here (e.g., "is this alarm active for today?") is scattered in `Controls` or `utils`.
- **Goal:** Move business logic into entities.
  - `AlarmDefinition` should have methods like `should_ring(time, weekday)`.
  - `AudioEffect` should manage its own configuration validation.

### 3. Presentation Logic in Domain Layer (Severity: Medium)
- **Problem:** `src/core/domain/mode_coordinator.py` and `edit_mode.py` manage UI navigation (menus, editing sessions). This is **Interface/Presentation logic**, not Domain logic.
- **Goal:** Move `ModeCoordinator`, `AlarmEditingSession`, and related "View" state management to `core/interface/presentation/` or `core/application/coordination/`. The Domain should only care about the *state* of the system (e.g., "Alarm Ringing"), not the *view* (e.g., "Editing Alarm Property X").

### 4. Infrastructure Leakage into Domain (Severity: Medium)
- **Problem:** `src/core/domain/model.py` imports `PIL.Image` (Display) and `jsonpickle` (Persistence).
- **Goal:**
  - Remove `PIL` from domain models. Domain objects should provide data; the Interface layer converts that to images.
  - Decouple persistence. Use Repositories (`IAlarmRepository`) instead of direct serialization in models or implicit event-based persistence.

## Architecture Overview

### Layers
- **Domain (`core/domain`):** Entities, Value Objects, Domain Events. **MUST BE PURE PYTHON.** (No `PIL`, `tornado`, `vlc`).
- **Application (`core/application`):** Services that orchestrate domain objects. `api.py` (Web), `di_container.py` (Wiring).
- **Infrastructure (`core/infrastructure`):** Implementations of interfaces. `audio.py` (VLC), `persistence.py` (File I/O), `scheduler.py` (APScheduler).
- **Interface (`core/interface`):** Entry points and UI. `display/` (OLED), `web/` (Tornado Handlers), `hardware_input_handler.py`.

### Key Components
```
src/
  app_clock.py          # Entry point, wiring
  core/
    domain/             # PURE BUSINESS LOGIC
      model.py          # Entities (AlarmDefinition, Config)
      events.py         # Domain Events (AlarmTriggered, VolumeChanged)
    application/
      controls.py       # [LEGACY] God class, to be refactored
      api.py            # Web API
    infrastructure/
      audio.py          # VLC wrapper
      persistence.py    # Event-based file saving
      event_bus.py      # In-memory event dispatcher
    interface/
      display/          # Visuals
      hardware_input_handler.py # Input mapping
```

## Development Workflows

**To run the application locally for development and testing:**
Dont forget to run python from the created virtual environment. It is not sufficient to just run "python3" if your system python points to a different version or installation.

**Run on Development Machine:**
```bash
./.venv-*/python3 src/app_clock.py --software
# Uses dummy display, keyboard controls (1=CCW, 2=CW, 3=mode, 4=invoke, 5=brightness)
```
the * denotes the latest created virtual environment

**Run on Raspberry Pi:**
```bash
./.venv-*/python3 src/app_clock.py
# Uses real hardware: SSD1322 OLED (SPI), MCP23017, BH1750
```
the * denotes the latest created virtual environment

## Critical Conventions

**Refactoring Guide:**
1. **New Features:** Do NOT add logic to `Controls`. Create a new Service or Domain Entity.
2. **Event Bus:** Continue using `EventBus` for decoupling, but prefer specific Domain Events (`AlarmSnoozed`) over generic property changes.
3. **Dependency Injection:** Always use `di_container.py`. Never instantiate infrastructure classes directly in the domain.

**Common Pitfalls to Avoid:**
- **Don't** import `core.infrastructure` or `core.interface` into `core.domain`.
- **Don't** put UI state (cursor position, current menu item) in the Domain Model.
- **Don't** use `Controls` as a dumping ground for new logic.
