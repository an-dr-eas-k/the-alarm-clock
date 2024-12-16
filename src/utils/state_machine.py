import logging

logger = logging.getLogger("utils.state_machine")


class StateMachineIdentifier:
    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    def __hash__(self):
        raise NotImplementedError("hash not implemented")


class Trigger(StateMachineIdentifier):
    pass


class State(StateMachineIdentifier):
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
        new_state: State,
        source_state_update: callable = None,
        destination_state_update: callable = None,
    ) -> "StateTransition":
        try:
            self.state_transition[trigger] = (
                new_state,
                source_state_update,
                destination_state_update,
            )
        except Exception as e:
            self.log.fatal(f"trigger to add: {trigger}")
            raise e
        return self

    def transition(self, trigger: Trigger) -> State:
        try:
            next_state = self.state_transition[trigger]
            destination_state = next_state[0]
            if next_state[1]:
                next_state[1](self.source_state)
            if next_state[2]:
                next_state[2](destination_state)
            return destination_state
        except Exception as e:
            return None


class StateMachine:
    def __init__(self, init_state: State):
        self.state_definition = {}
        self.current_state = init_state

    def do_state_transition(self, trigger: Trigger) -> State:
        try:
            st: StateTransition = self.state_definition[self.current_state]
            if not st:
                return self.current_state
            next_state = st.transition(trigger)
            if not next_state:
                return self.current_state
            logger.debug(
                f"state transition from {self.current_state.__class__.__name__} triggered by {trigger.__class__.__name__} to {next_state.__class__.__name__}"
            )
            self.current_state = next_state
            return self.current_state
        except Exception as e:
            raise (
                f"state transition from {self.current_state} with trigger {trigger} not defined!"
            ) from e

    def add_definition(self, transition: StateTransition):
        self.state_definition[transition.source_state] = transition
        return self


# class InvalidProgramException(Exception):
#     pass
# class StateEvent:
#     pass


# class State:
#     def next_state(self, event: StateEvent):
#         pass

#     pass


# class StateMachine:
#     pass


# using Newtonsoft.Json;

# using Roche.CptLinkService.Models.Extensions;
# using System;
# using System.Collections.Generic;
# using System.Linq;


# namespace Roche.CptLinkService.Business
# {
#   /// <summary>
#   /// class to define state transitions initiated by triggers.
#   /// </summary>
#   public class StateMachine<S, T> : StateMachine where T : Trigger
#   {
#     [JsonProperty]
#     private Dictionary<S, StateTransition<T, S>> stateDefinition = new Dictionary<S, StateTransition<T, S>>();

#     /// <summary>
#     /// performs the state transition
#     /// </summary>
#     /// <param name="entryState">source state</param>
#     /// <param name="t">trigger</param>
#     /// <returns>the result state</returns>
#     public S DoStateTransition(S entryState, T t)
#     {
#       try
#       {
#         return stateDefinition[entryState].Transition(t);
#       }
#       catch (Exception e)
#       {
#         throw new InvalidProgramException($"state transition from {entryState.ToString()} with trigger {t.ToDump()} not defined!", e);
#       }
#     }

#     /// <summary>
#     /// adds a state definition. the <see cref="StateTransition{T, S}"/> is defined for a given source state.
#     /// </summary>
#     /// <param name="sourceState"></param>
#     /// <param name="transition"></param>
#     /// <returns></returns>
#     public StateMachine<S, T> AddDefinition(S sourceState, StateTransition<T, S> transition)
#     {
#       stateDefinition.Add(sourceState, transition);
#       return this;
#     }
#   }

#   /// <summary>
#   /// trigger to init a state transition
#   /// </summary>
#   public class Trigger
#   {
#     override public bool Equals(object obj)
#     {
#       return GetHashCode() == obj.GetHashCode();
#     }
#     public override int GetHashCode()
#     {
#       return 0;
#     }
#   }

#   /// <summary>
#   /// defines the transitions by triggers from a given source state.
#   /// </summary>
#   public class StateTransition<T, S> : StateMachine
#   {

#     [JsonProperty]
#     private Dictionary<T, S> stateTransition = new Dictionary<T, S>();

#     /// <summary>
#     /// helper method to allow chaining when defining state transitions
#     /// </summary>
#     /// <param name="t"></param>
#     /// <param name="newState"></param>
#     /// <returns></returns>
#     public StateTransition<T, S> AddTransition(T t, S newState)
#     {
#       try
#       {
#         stateTransition.Add(t, newState);
#       }
#       catch (Exception)
#       {
#         log.Fatal($"trigger to add: {t.ToDump()}");
#         throw;
#       }
#       return this;
#     }

#     public S Transition(T t)
#     {
#       return stateTransition[t];
#     }
#   }

#   public class StateMachine
#   {
#     protected readonly static log4net.ILog log = log4net.LogManager.GetLogger(System.Reflection.MethodBase.GetCurrentMethod().DeclaringType);

#     protected StateMachine() { }
#   }
# }
