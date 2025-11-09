import logging
from typing import Type

from core.infrastructure.event_bus import BaseEvent, EventBus
from utils.extensions import T

logger = logging.getLogger("utils.state_machine")


class StateMachineIdentifier:
    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    def __hash__(self):
        return self.__str__().__hash__()

    def __str__(self):
        return self.__class__.__name__


class Trigger(StateMachineIdentifier):
    pass


class State(StateMachineIdentifier):
    proceedingState: Type[T] = None  # todo: remove?
    pass


class StateTransition:
    log = logging.getLogger(__name__)

    def __init__(self, source_state: State):
        super().__init__()
        self.source_state = source_state
        self.state_transition = {}

    def add_transition(
        self,
        trigger: Trigger,
        new_state_type: Type[T],
        eventToEmit: BaseEvent = None,
        source_state_updater: callable = None,
    ) -> "StateTransition":
        try:
            self.state_transition[trigger] = (
                new_state_type,
                eventToEmit,
                source_state_updater,
            )
        except Exception as e:
            self.log.fatal(f"trigger to add: {trigger}")
            raise e
        return self

    def transition(self, trigger: Trigger):
        try:
            return self.state_transition[trigger]
        except Exception:
            return None


class StateMachine:
    def __init__(self, event_bus: EventBus, init_state: State):
        self.state_definition = {}
        self.current_state = init_state
        self.event_bus = event_bus
        self.event_bus.on(Trigger)(self._transition_state)

    def _transition_state(self, trigger: Trigger) -> State:
        str_of_current_state = str(self.current_state)
        st: StateTransition = self.state_definition[self.current_state]
        if not st:
            logger.debug(f"no statetransition found for {str_of_current_state}")
            return self.current_state
        transition: tuple[Type[T], BaseEvent] = st.transition(trigger)
        if not transition:
            logger.debug(
                f"no transition defined from {str_of_current_state} triggered by {trigger}"
            )
            return self.current_state
        (next_state_type, eventToEmit, source_state_updater) = transition
        if source_state_updater:
            source_state_updater(self.current_state)
        next_state = None
        if self.current_state.proceedingState:
            next_state = self.current_state.proceedingState(self.current_state)
        else:
            next_state = next_state_type(self.current_state)
        if eventToEmit:
            self.event_bus.emit(eventToEmit)
        logger.debug(
            f"state transition from {str_of_current_state} triggered by {trigger} to {next_state}"
        )
        self.current_state = next_state
        return self.current_state

    def add_definition(self, transition: StateTransition) -> "StateMachine":
        self.state_definition[transition.source_state] = transition
        return self
