import unittest

from catalog import find_product


class CatalogueTests(unittest.TestCase):
    def test_lookup_normalizes_external_sku(self) -> None:
        self.assertEqual(find_product({"ABC-7": "Keyboard"}, "  abc-7 "), "Keyboard")

    def test_missing_sku_remains_missing(self) -> None:
        self.assertIsNone(find_product({"ABC-7": "Keyboard"}, "other"))


if __name__ == "__main__":
    unittest.main()
