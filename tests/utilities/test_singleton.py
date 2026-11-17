import unittest

from utils.singleton import singleton


class SingletonDecoratorTest(unittest.TestCase):
    def test_repeated_calls_return_same_instance(self):
        @singleton
        class Thing:
            def __init__(self):
                pass

        self.assertIs(Thing(), Thing())

    def test_constructor_runs_only_once(self):
        calls = []

        @singleton
        class Thing:
            def __init__(self, value):
                calls.append(value)
                self.value = value

        first = Thing(1)
        second = Thing(2)

        self.assertIs(first, second)
        self.assertEqual(second.value, 1)
        self.assertEqual(calls, [1])

    def test_constructor_arguments_are_forwarded(self):
        @singleton
        class Thing:
            def __init__(self, a, b=0):
                self.a, self.b = a, b

        thing = Thing(1, b=2)
        self.assertEqual((thing.a, thing.b), (1, 2))

    def test_different_classes_have_independent_instances(self):
        @singleton
        class A:
            pass

        @singleton
        class B:
            pass

        self.assertIsNot(A(), B())
        self.assertIsInstance(A(), object)

    def test_separately_decorated_classes_do_not_share_state(self):
        def make():
            @singleton
            class Thing:
                pass

            return Thing

        self.assertIsNot(make()(), make()())

    def test_failing_constructor_does_not_cache_instance(self):
        attempts = []

        @singleton
        class Flaky:
            def __init__(self):
                attempts.append(1)
                if len(attempts) == 1:
                    raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            Flaky()
        instance = Flaky()
        self.assertIs(instance, Flaky())
        self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
