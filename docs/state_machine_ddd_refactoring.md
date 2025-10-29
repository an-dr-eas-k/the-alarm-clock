# State Machine DDD Refactoring Plan

## Problems with Current Implementation

1. **Infrastructure Leakage**: State machine uses `HwButton("mode_button")` as triggers—domain knows hardware names
2. **Not a Relay**: Transitions mutate state but don't emit domain events for other components
3. **Mixed Event Systems**: Uses both `TACEvent` (observer) and `EventBus` (domain events)

## DDD-Aligned Architecture (Simplified)

### Principle: Upgrade Hardware Events to Domain Triggers

**The state machine already knows the context** (current state), so it should directly receive domain-level triggers, not hardware-specific ones. The translation happens at the infrastructure boundary, not in a separate translator.

```
Hardware Layer (Infrastructure)
    ↓ emits HwButtonEvent(device=MODE_BUTTON, direction=DOWN)
    ↓ immediately upgrades to domain trigger
    ↓ emits ButtonPressedEvent(button_name="mode_button") [DOMAIN EVENT]
Domain State Machine (Domain)
    ↓ receives domain events, knows state context
    ↓ transitions and emits domain events
    ↓ emits ModeChanged, AlarmSelected, etc.
Other Domain Services & UI (Domain/Interface)
```

### Key Insight: No InputTranslator Needed

The state machine **already has the state context** and **already has transition logic**. Creating an InputTranslator just duplicates this logic with cumbersome if-then-else conditions. Instead:

1. Hardware layer emits domain events (not infrastructure events)
2. State machine receives domain events and handles them based on current state
3. State machine emits domain events after transitions

### Flow Example

```
1. User presses mode button (Hardware)
   → ButtonManager detects hardware interrupt
   → ButtonManager.emit(ButtonPressedEvent(button_name="mode_button")) [domain event]

2. StateMachine listens to ButtonPressedEvent (Domain)
   → Current state: DefaultMode
   → Transition: DefaultMode + mode_button → AlarmViewMode
   → event_bus.emit(ModeChanged(previous='DefaultMode', new='AlarmViewMode'))

3. Display/Controls listen to ModeChanged (Interface/Application)
   → Update UI accordingly
```

**No duplicate logic**—the state machine already knows "mode_button in DefaultMode → go to AlarmViewMode"

## Refactoring Steps

### Step 1: Upgrade Hardware Events to Domain Events

Change hardware managers to emit domain events instead of infrastructure events:

```python
# core/infrastructure/mcp23017/buttons.py
class ButtonsManager:
    def __init__(self, mcp_manager: MCPManager, event_bus: EventBus = None):
        # ... existing ...
    
    def _on_mode_button_down(self, channel):
        # OLD: self.event_bus.emit(HwButtonEvent(...))
        # NEW: Emit domain event directly
        self.event_bus.emit(ButtonPressedEvent(button_name="mode_button"))
    
    def _on_invoke_button_down(self, channel):
        self.event_bus.emit(ButtonPressedEvent(button_name="invoke_button"))
```

```python
# core/infrastructure/mcp23017/rotary_encoder.py
class RotaryEncoderManager:
    def _handle_rotation(self):
        if clockwise:
            # OLD: self.event_bus.emit(HwRotaryEvent(...))
            # NEW: Emit domain event directly
            self.event_bus.emit(ButtonPressedEvent(button_name="rotary_clockwise"))
        else:
            self.event_bus.emit(ButtonPressedEvent(button_name="rotary_counter_clockwise"))
```

**Key point**: The hardware layer immediately translates to domain concepts. No `HwButtonEvent` or `HwRotaryEvent` needed—just `ButtonPressedEvent` with a semantic name.

### Step 2: Refactor StateMachine to Use Domain Events as Triggers

The state machine currently uses `HwButton` triggers. Change to use `ButtonPressedEvent`:

```python
# utils/state_machine.py
class StateMachine:
    """
    Generic state machine that:
    - Listens to domain events as triggers
    - Emits domain events on transitions (relay pattern)
    """
    
    def __init__(self, init_state: State, event_bus: EventBus):
        self.current_state = init_state
        self.event_bus = event_bus
        self.state_definitions = {}
    
    def handle(self, event: BaseEvent):
        """
        Handle domain event as a trigger.
        Returns list of domain events to emit after transition.
        """
        # Find transition for this event type in current state
        transition = self._find_transition(event)
        if not transition:
            logger.debug(f"No transition for {type(event).__name__} in {self.current_state}")
            return
        
        # Execute transition
        (next_state_type, state_updater, event_emitter) = transition
        
        # Update current state (e.g., increment alarm index)
        if state_updater:
            state_updater(self.current_state)
        
        # Transition to next state
        previous_state = self.current_state
        if self.current_state.proceedingState:
            next_state = self.current_state.proceedingState(self.current_state)
        else:
            next_state = next_state_type(self.current_state)
        
        self.current_state = next_state
        
        # Emit domain events (relay pattern!)
        if event_emitter:
            events = event_emitter(previous_state, next_state)
            for evt in events:
                self.event_bus.emit(evt)
        
        # Always emit state change
        self.event_bus.emit(ModeChanged(
            previous_mode=str(previous_state),
            new_mode=str(next_state)
        ))
```

### Step 3: Refactor AlarmClockStateMachine Transitions

Change from `HwButton` triggers to domain event triggers:

```python
# core/domain/mode.py
class AlarmClockStateMachine(StateMachine):
    def __init__(self, default_state, alarm_view_state, alarm_edit_state, property_edit_state, event_bus):
        StateMachine.__init__(self, default_state, event_bus)
        
        # Register as listener for button events
        self.event_bus.register(ButtonPressedEvent, self.handle)
        
        # Define transitions using button names (domain concept)
        self._register_transitions(
            default_state, alarm_view_state, alarm_edit_state, property_edit_state
        )
    
    def _register_transitions(self, default_mode, alarm_view_mode, alarm_edit_mode, property_edit_mode):
        
        # DefaultMode transitions
        self.add_definition(
            StateTransition(default_mode)
            .add_transition(
                trigger=lambda e: e.button_name == "mode_button",
                new_state_type=AlarmViewMode,
                event_emitter=lambda prev, next: []  # ModeChanged auto-emitted
            )
            .add_transition(
                trigger=lambda e: e.button_name == "rotary_clockwise",
                new_state_type=DefaultMode,
                event_emitter=lambda prev, next: [
                    VolumeChangeRequested(direction="up")
                ]
            )
            .add_transition(
                trigger=lambda e: e.button_name == "rotary_counter_clockwise",
                new_state_type=DefaultMode,
                event_emitter=lambda prev, next: [
                    VolumeChangeRequested(direction="down")
                ]
            )
        )
        
        # AlarmViewMode transitions
        self.add_definition(
            StateTransition(alarm_view_mode)
            .add_transition(
                trigger=lambda e: e.button_name == "mode_button",
                new_state_type=DefaultMode,
                event_emitter=lambda prev, next: []
            )
            .add_transition(
                trigger=lambda e: e.button_name == "rotary_clockwise",
                new_state_type=AlarmViewMode,
                state_updater=lambda state: state.activate_next_alarm(),
                event_emitter=lambda prev, next: [
                    AlarmSelected(alarm_index=next.alarm_index, is_new=False)
                ]
            )
            .add_transition(
                trigger=lambda e: e.button_name == "invoke_button",
                new_state_type=AlarmEditMode,
                event_emitter=lambda prev, next: [
                    AlarmEditStarted(alarm_index=next.alarm_index)
                ]
            )
        )
        
        # ... etc for other states
```

### Step 4: Remove TACEventPublisher from StateMachine

The state machine no longer needs the old observer pattern:

```python
# Before:
class AlarmClockStateMachine(StateMachine, TACEventPublisher):
    def handle(self, observation: TACEvent) -> State:
        if not isinstance(observation.reason, Trigger):
            return self.current_state
        # ...

# After:
class AlarmClockStateMachine(StateMachine):
    def handle(self, event: ButtonPressedEvent):
        # State machine logic based on event
        # Emits domain events via event_bus
```

### Step 5: Update StateTransition to Support Event Emitters

```python
# utils/state_machine.py
class StateTransition:
    def add_transition(
        self,
        trigger: callable,  # Predicate: event → bool
        new_state_type: Type[T],
        state_updater: callable = None,
        event_emitter: callable = None,  # NEW: returns list of events to emit
    ) -> "StateTransition":
        self.state_transition[trigger] = (new_state_type, state_updater, event_emitter)
        return self
```

## Migration Strategy

1. **Phase 1**: Hardware emits `ButtonPressedEvent` (domain) instead of `HwButtonEvent` (infrastructure)
2. **Phase 2**: Add `event_emitter` parameter to `StateTransition` (backwards compatible)
3. **Phase 3**: Refactor state machine to emit domain events on transitions
4. **Phase 4**: Migrate consumers (Controls, Display) to listen to domain events
5. **Phase 5**: Remove `TACEventPublisher` inheritance from state machine
6. **Phase 6**: Clean up old `TACEvent` observer pattern

## Benefits

✅ **No Code Duplication**: State machine already has context, no InputTranslator needed  
✅ **True Relay Pattern**: State machine receives domain events, emits domain events  
✅ **Simple Translation**: Hardware → domain event happens at infrastructure boundary  
✅ **Domain Purity**: `ButtonPressedEvent` is domain concept, not `HwButtonEvent`  
✅ **Testability**: Can test state machine with `ButtonPressedEvent`, no hardware needed  
✅ **Flexibility**: Easy to add new input methods (web UI emits same `ButtonPressedEvent`)  
✅ **Event Sourcing Ready**: All transitions emit events, enabling audit log  

## Why No InputTranslator?

The original suggestion had an `InputTranslator` that would:
```python
if isinstance(current_state, DefaultMode) and button == "mode":
    emit(EnterAlarmView())
elif isinstance(current_state, AlarmViewMode) and button == "mode":
    emit(EnterDefault())
```

**This duplicates the state machine's logic!** The state machine already knows:
```python
StateTransition(DefaultMode).add_transition(
    trigger=lambda e: e.button_name == "mode_button",
    new_state_type=AlarmViewMode
)
```

Why maintain two parallel if-then-else trees? Just use the state machine directly.

## Domain Events as Triggers

`ButtonPressedEvent(button_name="mode_button")` is a **domain event**, not infrastructure:
- Represents the semantic user action "mode button pressed"
- Could come from hardware, web UI, voice command, test suite
- The *name* is domain language ("mode", "invoke"), not hardware ("GPIO pin 17")

The state machine receives this domain event and:
1. Uses current state context to determine transition
2. Emits domain events about what happened (`ModeChanged`, `AlarmSelected`)

**Single responsibility, no duplication.**
