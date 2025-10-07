import math

a = 100
d = 55
epsilon: float = 75

c = lambda a, d, epsilon: a + d / math.tan(math.radians(epsilon))
b = lambda a, d, epsilon: d / math.sin(math.radians(epsilon))
print(
    "a = %d, b = %.2f, c = %.2f, d = %d, epsilon = %.2f"
    % (a, b(a, d, epsilon), c(a, d, epsilon), d, epsilon)
)
