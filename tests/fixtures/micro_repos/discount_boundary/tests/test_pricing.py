import unittest

from pricing import discount_rate


class DiscountRateTests(unittest.TestCase):
    def test_below_boundary_has_no_discount(self) -> None:
        self.assertEqual(discount_rate(99), 0)

    def test_boundary_is_eligible(self) -> None:
        self.assertEqual(discount_rate(100), 10)

    def test_above_boundary_remains_eligible(self) -> None:
        self.assertEqual(discount_rate(101), 10)


if __name__ == "__main__":
    unittest.main()
