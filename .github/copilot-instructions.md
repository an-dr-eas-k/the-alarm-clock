# The Alarm Clock - AI Coding Agent Instructions

## Domain-Driven Design (DDD) Vision

**Long-term architectural goal:**
This project should evolve towards a clear **Domain-Driven Design (DDD)** architecture. DDD emphasizes modeling the core business domain, using rich domain models, explicit boundaries (bounded contexts), and a ubiquitous language shared between code and stakeholders. Technical patterns (event-driven, DI, state machines) should support—not overshadow—the domain model.

**Key DDD Principles to Guide Development:**
- **Rich Domain Model:** Business logic should reside in domain models (entities, value objects, aggregates) in `core/domain/`.
- **Bounded Contexts:** Define clear boundaries for subdomains (e.g., Alarm, Playback, HardwareControl) and keep their logic isolated.
- **Ubiquitous Language:** Use business terms for class, method, and event names. Document domain concepts in code and instructions.
- **Separation of Concerns:**
  - **Domain Layer:** Pure business logic, no infrastructure dependencies.
  - **Application Layer:** Orchestrates domain logic, coordinates tasks, but does not contain business rules.
  - **Infrastructure Layer:** Implements technical details (audio, persistence, hardware), replaceable via interfaces.
  - **Interface Layer:** Handles user and system interfaces (display, web, API).
- **Domain Events:** Use events to represent business facts (e.g., `AlarmTriggered`), not just technical changes.
- **Repositories:** Use repository interfaces for persistence, implemented in infrastructure.

**Transition Guidance:**
- When adding new features, prefer placing business logic in domain models.
- Refactor existing logic from infrastructure/application into the domain layer where possible.
- Use interfaces and dependency injection to decouple domain from infrastructure.
- Document and enforce bounded contexts and ubiquitous language.

## Architecture Overview

This is a **Raspberry Pi-based alarm clock** with physical hardware controls (OLED display, rotary encoder, buttons, light sensor, audio output) and Spotify integration. The architecture currently follows **event-driven design** with **dependency injection** and a **state machine** pattern, but is intended to evolve towards a clear **DDD (Domain-Driven Design)** structure.


### Core Patterns (Current and Future DDD Direction)

The following technical patterns are currently used as enablers, but the long-term goal is to ensure that all business logic resides in the domain layer, following DDD principles. As the project evolves, introduce DDD-specific patterns (domain events, aggregates, repositories) and ensure technical mechanisms serve the domain model, not the other way around.

**Observer Pattern via TAC Events:**
- `TACEventPublisher` publishes property changes and events. In the future, prefer domain events that represent business facts (e.g., `AlarmTriggered`) and keep event handling logic within the domain layer where possible.
- `TACEventSubscriber` handles events via `handle(observation: TACEvent)` method.
- Components subscribe to each other in `app_clock.py` (e.g., `context.subscribe(playback_content)`).
- During subscription, publishers automatically send current state via `during_registration=True` events.

**Dependency Injection:**
- All components are wired in `core/application/di_container.py` using `dependency-injector`.
- Use `providers.Singleton` for long-lived services, `providers.Factory` for runtime-created objects.
- When adding new dependencies: add provider to `DIContainer`, inject via constructor parameters.
- Over time, use DI to inject domain services, repositories, and infrastructure adapters, keeping the domain layer free of technical dependencies.

**State Machine:**
- `AlarmClockStateMachine` in `core/domain/mode.py` manages UI states (Default, AlarmView, AlarmEdit, PropertyEdit).
- States transition via `HwButton` triggers (rotary encoder, buttons).
- State transitions defined with `.add_transition(trigger, new_state_type, optional_updater)`.
- See `utils/state_machine.py` for the generic state machine implementation.
- In the future, ensure state transitions and business rules are modeled as part of the domain logic, not just UI logic.

**Factory Pattern for Players:**
- `PlayerFactory` (implements `IPlayerFactory`) creates media players based on `AudioEffect` type.
- Injected into `Speaker` to separate player creation logic from usage.
- When adding new player types: update `PlayerFactory.create_player()` method.
- As DDD patterns are adopted, use factories for aggregate creation and keep player instantiation logic outside the domain layer.

## Key Components

```
src/
  app_clock.py          # Main entry point, wires all subscriptions
  core/
    application/
      di_container.py   # DI configuration (ADD NEW DEPENDENCIES HERE)
      api.py            # Tornado web API (port 8443 with TLS)
      controls.py       # Business logic, APScheduler jobs
    domain/
      model.py          # Domain models (Config, AudioEffect, etc.)
      mode.py           # State machine states and transitions
    infrastructure/
      audio.py          # VLC-based audio playback, PlayerFactory
      persistence.py    # JSON serialization to config.json
      brightness_sensor.py  # BH1750 light sensor via I2C
      mcp23017/         # Button/rotary encoder via MCP23017 port expander
    interface/
      display/          # OLED rendering (luma.oled, PIL)
      web/              # Tornado web UI templates
  utils/
    events.py           # TACEventPublisher/Subscriber base classes
    state_machine.py    # Generic state machine implementation
```

## Development Workflows

**Run on Development Machine:**
```bash
python3 src/app_clock.py --software
# Uses dummy display device, keyboard controls (1=CCW, 2=CW, 3=mode, 4=invoke, 5=brightness)
```

**Run on Raspberry Pi:**
```bash
python3 src/app_clock.py
# Uses real hardware: SSD1322 OLED (SPI), MCP23017 I2C port expander, BH1750 light sensor
```

**Install Dependencies:**
```bash
pip install -r requirements.txt
# Note: RPi.GPIO is uninstalled in production (see rpi/run.sh), uses rpi-lgpio instead
```

**Testing Changes:**
- Most modules have `if __name__ == "__main__"` blocks for standalone testing
- Example: `python3 src/core/infrastructure/audio.py` tests audio playback

## Critical Conventions

**Adding New Observable Properties:**
1. Add property to publisher class (e.g., `Config`, `PlaybackContent`)
2. Properties are auto-published on subscription (see `TACEventPublisher.subscribe()`)
3. Subscribers implement `handle(observation: TACEvent)` and check `observation.property_name`

**Adding New Dependencies:**
1. Define provider in `di_container.py` (e.g., `player_factory = providers.Singleton(PlayerFactory, config=config)`)
2. Import new class at top of `di_container.py`
3. Inject into dependent component's constructor
4. Wire subscriptions in `app_clock.py.go()` if event-driven

**Hardware vs Software Mode:**
- Check `argument_args().software` in DI container
- Hardware mode uses real devices; software mode uses mocks/keyboard input
- Override providers in `app_clock.py` for software mode (see `ComputerInfrastructure`)

**Audio Effects:**
- Three types: `StreamAudioEffect` (radio streams), `SpotifyAudioEffect`, `OfflineAlarmEffect`
- `PlayerFactory` creates appropriate `MediaPlayer` based on effect type
- VLC handles streaming; fallback uses `ogg123` for offline playback

**Configuration Persistence:**
- `Config` and `AlarmClockContext` changes auto-save via `Persistence` subscriber
- Files: `src/config.json` (main config), `src/resources/alarm_details.json` (active alarm)
- Uses `jsonpickle` for serialization

## Integration Points

**Spotify (via Raspotify/Librespot):**
- External librespot daemon posts events to `/libreSpotifyEvent` endpoint
- Handled by `LibreSpotifyEventHandler` in `api.py`
- Volume control bridges between VLC and ALSA (`utils/sound_device.py`)

**Web UI (Tornado):**
- HTTPS on port 8443 with TLS certs in `rpi/tls/`
- Template in `core/interface/web/template.html`
- API endpoints: `/config/*` (config management), `/action/*` (reboot/update)

**Hardware (I2C/SPI):**
- I2C bus 1: BH1750 light sensor (0x23), MCP23017 port expander (0x20)
- SPI: SSD1322 OLED display via luma.oled
- GPIO4: MCP23017 interrupt pin

**Scheduler (APScheduler):**
- Two job stores: `alarm_store` (alarm triggers), `default_store` (misc timers)
- Managed by `Controls` class
- Jobs: alarms, sun events (sunrise/sunset), volume meter hide timer

## Common Pitfalls

- **Don't** create players directly in `Speaker`—use `PlayerFactory`
- **Don't** forget to wire subscriptions in `app_clock.py` when adding new event-driven components
- **Do** use abstract base classes (ABC) for interfaces to support mocking (e.g., `IPlayerFactory`)
- **Do** call `publish(property='property_name')` after modifying observable properties
- **Do** check `observation.during_registration` to avoid side effects during initial subscription
- Hardware-specific code should check `is_on_hardware()` or be overridden in DI container

## Project-Specific Idioms

- Logger naming: `logger = logging.getLogger("tac.<component>")` (configured in `resources/logging.conf`)
- State machine states inherit from `TacMode(State)`, triggers use `HwButton("button_name")`
- Display presenters compose UI via `ComposableImage` pattern with PIL
- Rotary encoder: CW/CCW events trigger volume changes in `Controls.handle()`
