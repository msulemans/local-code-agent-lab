import unittest

from profiles import clean_display_name


class DisplayNameTests(unittest.TestCase):
    def test_surrounding_spaces_are_removed(self) -> None:
        self.assertEqual(clean_display_name("  Ada Lovelace  "), "Ada Lovelace")

    def test_every_whitespace_run_becomes_one_space(self) -> None:
        self.assertEqual(clean_display_name("Ada\t  Lovelace"), "Ada Lovelace")


if __name__ == "__main__":
    unittest.main()
