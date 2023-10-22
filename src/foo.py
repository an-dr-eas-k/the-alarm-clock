class parent:
	array : []

	def __init__(self) -> None:
		self.array = []
		self.array.append(0)

class child1(parent):
	def __init__(self) -> None:
		super().__init__()
		self.array.append(1)

class child2(parent):
	def __init__(self) -> None:
		super().__init__()
		self.array.append(2)


if __name__ == '__main__':
	print ("start")
	a = parent()
	b = child1()
	c = child2()

	print(a.array)
	print(b.array)
	print(c.array)


