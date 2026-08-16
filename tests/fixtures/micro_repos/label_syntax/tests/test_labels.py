import unittest

from labels import format_label


class LabelTests(unittest.TestCase):
    def test_label_is_trimmed_and_titled(self) -> None:
        self.assertEqual(format_label("  local code  "), "Local Code")


if __name__ == "__main__":
    unittest.main()
