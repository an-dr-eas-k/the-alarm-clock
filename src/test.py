import unittest
from resources.resources import init_logging
from utils.test_os import TestOS

if __name__ == "__main__":
    init_logging()
    test_suite = unittest.TestSuite()

    test_suite.addTest(unittest.makeSuite(TestOS))

    unittest.TextTestRunner(verbosity=2).run(test_suite)
