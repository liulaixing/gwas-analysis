import unittest
from lib.method.ld_prune.tsgpu_backend import invert_index


class TestLDPrune(unittest.TestCase):

    def test_invert_index(self):
        cases = [
            # Window = step + 1
            dict(
                window=4, step=3,
                indexes=[
                    (0, (0, 1, 0)),
                    (1, (0, 2, 0)),
                    (2, (0, 3, 0)),
                    (3, (0, 4, 0)),
                    (4, (1, 2, 0)),
                    (5, (1, 3, 0)),
                    (6, (1, 4, 0)),
                    (7, (2, 3, 0)),
                    (8, (2, 4, 0)),
                    (9, (0, 1, 1)),
                ]
            ),
            # Window >> step
            dict(
                window=5, step=1,
                indexes=[
                    (0, (0, 1, 0)),
                    (1, (0, 2, 0)),
                    (2, (0, 3, 0)),
                    (3, (0, 4, 0)),
                    (4, (0, 5, 0)),
                    (5, (0, 1, 1)),
                ]
            ),
            # Window = step but > 1
            dict(
                window=3, step=3,
                indexes=[
                    (0, (0, 1, 0)),
                    (1, (0, 2, 0)),
                    (2, (0, 3, 0)),
                    (3, (1, 2, 0)),
                    (4, (1, 3, 0)),
                    (5, (2, 3, 0)),
                    (6, (0, 1, 1)),
                ]
            ),
            # Window = step = 1
            dict(
                window=1, step=1,
                indexes=[
                    (0, (0, 1, 0)),
                    (1, (0, 1, 1)),
                ]
            ),
        ]

        for case in cases:
            w, s = case['window'], case['step']
            for c in case['indexes']:
                i, expected = c
                actual = invert_index(i, w, s)
                self.assertEqual(actual, expected)

                def test_period_increment(case, inc, expected):
                    # Move index forward by `inc` periods and assert that results do not change
                    # e.g. if there are 9 comparisons in a slice, check that index 0 has same result as index 9
                    actual = invert_index(i + inc * (len(case['indexes']) - 1), w, s)
                    # Add inc to slice number since we have intentionally increased this
                    expected = expected[:-1] + (expected[-1] + inc,)
                    self.assertEqual(actual, expected)

                # Test small period shifts in index being inverted
                test_period_increment(case, 1, tuple(expected))
                test_period_increment(case, 2, tuple(expected))

                # Test large period shift
                test_period_increment(case, 20000, tuple(expected))

                # Test shift beyond int32 max
                test_period_increment(case, int(1E12), tuple(expected))


