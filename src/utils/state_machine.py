import logging
from typing import Callable, Type

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

    def __init__(self, starting_state):
        super().__init__()
        self.starting_state = starting_state
        self.state_transition = {}

    def add_transition(
        self,
        trigger: Trigger,
        next_state=None,
        eventToEmit: BaseEvent = None,
        callable: callable = None,
    ) -> "StateTransition":
        try:
            self.state_transition[trigger] = (
                next_state,
                eventToEmit,
                callable,
            )
        except Exception as e:
            self.log.fatal(f"trigger to add: {trigger}")
            raise e
        return self

    def transition(self, trigger: Trigger):
        try:
            return self.state_transition.get(trigger)
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
        st: StateTransition = self.state_definition.get(self.current_state)
        if not st:
            logger.debug(f"no statetransition found for {str_of_current_state}")
            return self.current_state
        transition = st.transition(trigger)
        if not transition:
            logger.debug(
                f"no transition defined from {str_of_current_state} triggered by {trigger}"
            )
            return self.current_state
        (next_state, eventToEmit, callable) = transition
        if callable:
            callable(self.current_state)
        if next_state and isinstance(next_state, Callable):
            next_state = next_state(self.current_state)
        if not next_state:
            next_state = self.current_state
        if eventToEmit:
            self.event_bus.emit(eventToEmit)
        logger.debug(
            f"state transition from {str_of_current_state} triggered by {trigger} to {next_state}"
        )
        self.current_state = next_state
        return self.current_state

    def add_definition(self, transition: StateTransition) -> "StateMachine":
        self.state_definition[transition.starting_state] = transition
        return self
