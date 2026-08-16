import unittest

from accounts import can_save_username
from preview import can_preview_username


class UsernameConsistencyTests(unittest.TestCase):
    def test_three_character_boundary_is_allowed_everywhere(self) -> None:
        self.assertTrue(can_preview_username("  ada "))
        self.assertTrue(can_save_username("  ada "))

    def test_short_names_are_rejected_everywhere(self) -> None:
        self.assertFalse(can_preview_username("ab"))
        self.assertFalse(can_save_username("ab"))

    def test_longer_names_remain_allowed_everywhere(self) -> None:
        self.assertTrue(can_preview_username("grace"))
        self.assertTrue(can_save_username("grace"))


if __name__ == "__main__":
    unittest.main()
