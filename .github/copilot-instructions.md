# The Alarm Clock - AI Coding Agent Instructions

## Architecture Standards (Domain-Driven Design)

**Architecture Style:**
This project follows a clean **Domain-Driven Design (DDD)** architecture. All new code must adhere to these principles.

**Key Principles:**
- **Rich Domain Model:** Business logic resides in `core/domain/`. Entities encapsulate both data and behavior.
- **Bounded Contexts:**
  - **Alarm Context:** Scheduling, triggering, and recurring rules.
  - **Audio Context:** Playback, volume, streams, and Spotify integration.
  - **Hardware Context:** Input handling (buttons, rotary) and sensors.
  - **UI Context:** Display rendering and menu navigation.
- **Ubiquitous Language:** Use consistent business terms (`AlarmDefinition`, `AudioStream`, `WakeUpSequence`).
- **Dependency Rule:** Domain layer must NOT depend on Infrastructure or Interface layers.

## Refactoring Roadmap & Current Status

The project is transitioning from a monolithic architecture to DDD. `Controls` has been removed, but further decoupling is needed.

### 1. Refine Application Services (Priority: High)
- **Status:** `Controls` has been replaced by `AlarmAudioService` (inheriting from `BasicAudioService`) and `SystemService`.
- **Problem:** `AlarmAudioService` couples Alarm logic with Audio logic via inheritance.
- **Action:**
  - **Create `AlarmService`:** Extract scheduling, triggering, and snoozing logic into a dedicated service.
  - **Refine `AudioService`:** Ensure `BasicAudioService` (or a renamed `AudioService`) handles ONLY volume and playback.
  - **Decouple:** `AlarmService` should *use* `AudioService` (via DI or Events), not inherit from it.

### 2. Purify Domain Models (Priority: High)
- **Status:** `src/core/domain/model.py` imports `PIL.Image` (Presentation) and `jsonpickle` (Infrastructure).
- **Action:**
  - **Remove `PIL`:** Domain entities should provide data (text, paths, values). The Interface layer (Display) should convert this to Images.
  - **Remove `jsonpickle`:** Replace direct serialization with a Repository pattern (`IAlarmRepository`) implemented in Infrastructure.

### 3. Separate Presentation from Domain (Priority: Medium)
- **Status:** `src/core/domain/mode_coordinator.py` and `edit_mode.py` manage UI navigation and editing sessions.
- **Action:**
  - Move these files to `core/interface/presentation/` or `core/application/coordination/`.
  - The Domain should only track system state (e.g., "Alarm Ringing"), not UI state (e.g., "Cursor at line 3").

### 4. Enrich Domain Entities (Priority: Medium)
- **Status:** `AlarmDefinition` and `AudioEffect` are still largely data structures.
- **Action:**
  - Move validation and business rules (e.g., "Is this alarm active today?") from Services/Utils into these Entities.

## Architecture Overview

### Layers
- **Domain (`core/domain`):** Entities, Value Objects, Domain Events. **MUST BE PURE PYTHON.** (No `PIL`, `tornado`, `vlc`).
- **Application (`core/application`):** Services that orchestrate domain objects. `api.py`, `system_service.py`, `di_container.py`.
- **Infrastructure (`core/infrastructure`):** Implementations. `audio.py` (VLC), `persistence.py` (File I/O), `scheduler.py` (APScheduler).
- **Interface (`core/interface`):** Entry points and UI. `display/` (OLED), `web/` (Tornado), `hardware_input_handler.py`.

### Key Components
```
src/
  app_clock.py          # Entry point
  core/
    domain/             # PURE BUSINESS LOGIC
      model.py          # Entities
      events.py         # Domain Events
    application/
      alarm_audio_service.py # [Refactor Target] Split into AlarmService + AudioService
      system_service.py      # System tasks (Wifi, Weather)
      api.py                 # Web API
      di_container.py        # Dependency Injection
    infrastructure/
      audio.py          # VLC wrapper
      persistence.py    # File I/O
      event_bus.py      # In-memory dispatcher
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

1.  **New Features:** Do NOT add logic to `AlarmAudioService`. Create a new Service or Domain Entity.
2.  **Event Bus:** Use specific Domain Events (`AlarmSnoozed`) over generic property changes.
3.  **Dependency Injection:** Always use `di_container.py`. Never instantiate infrastructure classes directly in the domain.
4.  **No Circular Imports:** Be careful when extracting services. Use `TYPE_CHECKING` imports where necessary.
5.  **luma.oled Device:** Always use `RGB` mode for compatibility, with the luma display. The pillow image rendered with device.display() must be in RGB mode.
