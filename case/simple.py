import math

a = 60
d = 65
epsilon : float = 75

c = lambda a, d, epsilon: 1 / math.tan(math.radians(epsilon)) * ( d + ((a/math.cos(math.radians(epsilon)) ) ** 2 - a ** 2) ** (1/2) )

b1 = lambda a, c, epsilon: (c-a)/math.cos(math.radians(epsilon))
b = lambda a, d, epsilon: b1(a, c(a, d, epsilon), epsilon)

print ("a = %d, b = %.2f, c = %.2f, d = %d, epsilon = %.2f" % (a, b(a, d, epsilon), c(a, d, epsilon), d, epsilon))