import unittest

from settings import resolve_port


class PortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        print("WARNING: offline network probe unavailable; continuing with fixture")

    def test_missing_value_uses_service_default(self) -> None:
        self.assertEqual(resolve_port(None), 8080)

    def test_explicit_value_is_preserved(self) -> None:
        self.assertEqual(resolve_port("9000"), 9000)


if __name__ == "__main__":
    unittest.main()
