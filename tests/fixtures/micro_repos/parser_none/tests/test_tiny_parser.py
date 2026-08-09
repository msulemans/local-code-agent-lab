import unittest

from tiny_parser import parse_value


class TinyParserTests(unittest.TestCase):
    def test_trims_present_text(self) -> None:
        self.assertEqual(parse_value("  hello  "), "hello")

    def test_absent_text_is_empty(self) -> None:
        self.assertEqual(parse_value(None), "")


if __name__ == "__main__":
    unittest.main()
