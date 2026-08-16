import unittest

from metrics import success_ratio


class RatioTests(unittest.TestCase):
    def test_empty_sample_is_zero(self) -> None:
        self.assertEqual(success_ratio(3, 0), 0.0)

    def test_non_empty_sample_is_divided(self) -> None:
        self.assertEqual(success_ratio(3, 4), 0.75)


if __name__ == "__main__":
    unittest.main()
