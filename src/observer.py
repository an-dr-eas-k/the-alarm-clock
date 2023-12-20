import re

class Observation:
	during_registration: bool
	reason: str = None
	property_name: str = None
	new_value: any = None
	observable: any = None

	def __init__(self, property_name: str = None, reason: str = None, during_registration: bool = False, observable: any = None) -> None:
		assert property_name or reason
		self.during_registration = during_registration
		self.reason = reason
		self.property_name = property_name
		self.observable = observable

	def to_string(self):
		property_segment = ""
		if self.property_name:
			property_segment = f"property {self.property_name}={self.new_value}"
		reason_segment = ""
		if self.reason:
			reason_segment = f"reason {self.reason}"
		return f"observation {self.observable.__class__.__name__}: {reason_segment}{property_segment}"


class Observer:

	def update(self, observation: Observation):
		print(f"{self.__class__.__name__} is notified: {observation.to_string()}")

class Observable:
	observers : []

	def __init__(self):
		self.observers = []

	def notify(self, property=None, reason = None, during_registration: bool = False):

		o: Observation
		if property:
			assert property in dir(self)
			o = Observation(property_name=property, during_registration=during_registration, observable=self)
			o.new_value = self.__getattribute__(o.property_name)
		else:
			o = Observation(reason=reason, during_registration=during_registration, observable=self)

		for observer in self.observers:
			assert isinstance(observer, Observer)
			observer.update( o )

	def attach(self, observer: Observer):
		assert isinstance(observer, Observer)
		self.observers.append(observer)
		properties = [
			attr for attr in dir(self) 
			if True
				and attr != 'observers'
				and not re.match(r"^__.*__$", attr) 
				and hasattr(self, attr) 
				and not callable(getattr(self, attr)) ]
		for property_name in properties:
			try:
				self.notify(property=property_name, during_registration=True) 
			except:
				pass

	def __getstate__(self):
		state = self.__dict__.copy()
		del state['observers']
		return state

	def __setstate__(self, state):
		state['observers'] = []
		self.__dict__.update(state)
