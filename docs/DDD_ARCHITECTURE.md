# Domain-Driven Design Architecture

## Layer Overview

This project follows **Domain-Driven Design (DDD)** principles with clear separation of concerns across four layers:

```
┌─────────────────────────────────────────────────────────┐
│                    INTERFACE LAYER                       │
│  (User interaction, Hardware I/O, API endpoints)        │
│                                                          │
│  • display/display_content.py  (ViewModel - MVVM)       │
│  • display/presenter.py         (View logic)             │
│  • display/format.py            (Display formatting)     │
│  • hardware_input_handler.py   (Hardware → Domain)      │
│  • web/template.html            (Web UI)                 │
└─────────────────────────────────────────────────────────┘
                          ↓ depends on
┌─────────────────────────────────────────────────────────┐
│                   APPLICATION LAYER                      │
│  (Use cases, orchestration, workflows)                  │
│                                                          │
│  • controls.py                  (Main orchestrator)      │
│  • api.py                       (REST API handlers)      │
│  • di_container.py              (Dependency injection)   │
└─────────────────────────────────────────────────────────┘
                          ↓ depends on
┌─────────────────────────────────────────────────────────┐
│                     DOMAIN LAYER                         │
│  (Pure business logic, no technical dependencies)       │
│                                                          │
│  Aggregates:                                             │
│  • AlarmClockContext            (Aggregate Root)         │
│  • EnvironmentContext           (Environment state)      │
│  • Config                       (Configuration)          │
│                                                          │
│  Entities:                                               │
│  • AlarmDefinition              (Alarm configuration)    │
│  • AlarmClockModeCoordinator    (UI mode management)     │
│                                                          │
│  Value Objects:                                          │
│  • RoomBrightness               (Display brightness)     │
│  • AudioStream, AudioEffect     (Audio configuration)    │
│  • VisualEffect                 (Alarm visual effects)   │
│                                                          │
│  Domain Events:                                          │
│  • AudioStreamChangedEvent                               │
│  • VolumeChangedEvent                                    │
│  • AlarmEvent                                            │
└─────────────────────────────────────────────────────────┘
                          ↓ depends on
┌─────────────────────────────────────────────────────────┐
│                 INFRASTRUCTURE LAYER                     │
│  (External systems, persistence, hardware)              │
│                                                          │
│  • audio.py                     (VLC playback)           │
│  • persistence.py               (JSON storage)           │
│  • brightness_sensor.py         (BH1750 sensor)          │
│  • event_bus.py                 (Event infrastructure)   │
│  • mcp23017/                    (Hardware buttons)       │
└─────────────────────────────────────────────────────────┘
```

## Key DDD Patterns Implemented

### 1. **Aggregates**

**AlarmClockContext** (Aggregate Root)
- Central entry point for domain operations
- Coordinates Config, EnvironmentContext, and ModeCoordinator
- Enforces invariants and business rules
- Location: `core/domain/model.py`

**EnvironmentContext** (Aggregate)
- Encapsulates environmental state (weather, network, location)
- Owned by AlarmClockContext
- Location: `core/domain/model.py`

### 2. **Value Objects**

**RoomBrightness**
- Immutable value representing ambient brightness
- Contains behavior: `is_highly_dimmed()`, `get_grayscale_value()`
- Used throughout the system for consistent brightness handling

**NextAlarmInfo**
- Immutable value representing next alarm timing
- Shields domain from infrastructure (APScheduler Job)
- Location: `core/interface/display/display_content.py`

### 3. **Entities**

**AlarmDefinition**
- Has identity (id field)
- Mutable lifecycle (can be edited, activated/deactivated)
- Rich domain behavior: `to_cron_trigger()`, `is_recurring()`

**AlarmClockModeCoordinator**
- Domain entity managing UI mode transitions
- Isolated from hardware through HardwareInputHandler

### 4. **Domain Events**

Events represent **business facts** that happened:
- `AlarmEvent` - An alarm was triggered
- `AudioStreamChangedEvent` - Audio source changed
- `VolumeChangedEvent` - Volume was adjusted
- `WifiStatusChangedEvent` - Network connectivity changed

Located in: `core/domain/events.py`

### 5. **Repositories** (Future Enhancement)

Currently using direct persistence, but planned:
```python
# core/repositories.py
class AlarmDefinitionRepository(ABC):
    @abstractmethod
    def get_by_id(self, id: int) -> AlarmDefinition: ...
    
    @abstractmethod
    def save(self, alarm: AlarmDefinition): ...
```

### 6. **Application Services**

**Controls** (Application Service)
- Orchestrates domain operations
- Coordinates between aggregates
- Manages scheduler and external systems
- Does NOT contain business logic (delegates to domain)

**AlarmEditingService** (Application Service)
- Manages alarm editing workflow
- Uses AlarmEditingSession aggregate
- Coordinates UI state with domain changes

### 7. **Anti-Corruption Layer**

**HardwareInputHandler** (Interface Layer)
- Translates hardware events (HwButtonEvent) to domain commands
- Prevents infrastructure leakage into domain
- Maps rotary encoder events to volume adjustments

**DisplayContent** (Interface Layer)
- ViewModel pattern (MVVM)
- Aggregates domain data for presentation
- Shields View from domain complexity

## Layering Rules (Dependency Inversion)

### ✅ Allowed Dependencies

```
Interface → Application → Domain → (nothing)
Infrastructure → Domain (via interfaces)
```

### ❌ Forbidden Dependencies

```
Domain → Infrastructure  ❌
Domain → Interface       ❌
Domain → Application     ❌
```

## Example: Adding a New Feature (DDD Way)

**Scenario:** Add "snooze alarm" feature

### 1. **Domain Layer** (Business Logic)
```python
# core/domain/model.py
class AlarmDefinition:
    def snooze(self, minutes: int = 10) -> datetime:
        """
        Business rule: Snooze moves alarm forward by configured minutes.
        Returns the new alarm time.
        """
        if not self.is_active:
            raise DomainException("Cannot snooze inactive alarm")
        
        snooze_time = GeoLocation().now() + timedelta(minutes=minutes)
        self.set_future_date(snooze_time.hour, snooze_time.minute)
        return snooze_time
```

### 2. **Application Layer** (Orchestration)
```python
# core/application/controls.py
def snooze_current_alarm(self):
    """
    Application service: Orchestrates snooze operation.
    """
    alarm_def = self._get_current_alarm()
    new_time = alarm_def.snooze(self.config.snooze_duration_mins)
    
    # Reschedule in infrastructure
    self.scheduler.add_job(...)
    
    # Emit domain event
    self.event_bus.emit(AlarmSnoozedEvent(new_time))
```

### 3. **Interface Layer** (User Interaction)
```python
# core/interface/hardware_input_handler.py
def _handle_snooze_button(self, event: HwButtonEvent):
    """
    Translate hardware button to domain command.
    """
    self.mode_coordinator.snooze_alarm()
```

### 4. **Infrastructure Layer** (External Systems)
```python
# core/infrastructure/audio.py
def stop_alarm_playback(self):
    """Stop VLC playback (infrastructure detail)."""
    self.player.stop()
```

## Benefits of This Architecture

### 1. **Testability**
- Domain logic testable without hardware
- Mock interfaces for infrastructure
- Unit test business rules in isolation

### 2. **Flexibility**
- Swap VLC for another audio player
- Replace JSON persistence with database
- Change display technology without touching domain

### 3. **Maintainability**
- Business logic concentrated in domain layer
- Clear responsibility boundaries
- Changes localized to appropriate layers

### 4. **Ubiquitous Language**
- Code speaks the business domain
- `AlarmDefinition.snooze()` not `schedule_timer()`
- `EnvironmentContext.is_daytime` not `check_sun_api()`

## Migration Path

### Current State (✅ Completed)
- [x] Domain layer separated from infrastructure
- [x] DisplayContent moved to interface layer
- [x] HardwareInputHandler as anti-corruption layer
- [x] Aggregates with clear boundaries

### Next Steps (Recommended)
- [ ] Extract PlaybackContent to interface layer
- [ ] Implement Repository pattern for persistence
- [ ] Move audio player creation to factory in infrastructure
- [ ] Add domain event sourcing for audit trail
- [ ] Create bounded contexts for complex domains

## File Organization

```
src/core/
├── domain/                    # PURE BUSINESS LOGIC
│   ├── model.py              # Aggregates, Entities, Value Objects
│   ├── mode_coordinator.py   # Mode management entity
│   ├── edit_mode.py          # Editing workflow
│   └── events.py             # Domain events
│
├── application/               # ORCHESTRATION
│   ├── controls.py           # Main application service
│   ├── api.py                # REST API handlers
│   └── di_container.py       # Dependency injection
│
├── interface/                 # USER/HARDWARE INTERACTION
│   ├── display/
│   │   ├── display_content.py    # ViewModel (THIS IS KEY!)
│   │   ├── presenter.py          # View logic
│   │   └── format.py             # Display formatting
│   ├── hardware_input_handler.py # Hardware → Domain
│   └── web/                      # Web interface
│
└── infrastructure/            # EXTERNAL SYSTEMS
    ├── audio.py              # VLC integration
    ├── persistence.py        # JSON storage
    ├── event_bus.py          # Event infrastructure
    └── mcp23017/             # Hardware drivers
```

## Key Takeaway

**The domain layer knows NOTHING about:**
- Display technology (OLED, TFT, etc.)
- Audio players (VLC, mpg123, etc.)
- Persistence (JSON, SQLite, etc.)
- Hardware (buttons, sensors, etc.)
- Web frameworks (Tornado, Flask, etc.)

**The domain layer knows ONLY:**
- Alarms can be snoozed
- Alarms have recurrence patterns
- Volume has min/max limits
- Weather affects display brightness

This is the essence of Domain-Driven Design!
