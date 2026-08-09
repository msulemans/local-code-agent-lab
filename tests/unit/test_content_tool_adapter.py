import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from analyze_content_tool_adapter import parse_content_tool_call  # noqa: E402


class ContentToolAdapterTests(unittest.TestCase):
    def test_accepts_one_exact_tool_object(self) -> None:
        call = parse_content_tool_call('{"name":"read_file","arguments":{"path":"README.md"}}')

        self.assertEqual(call["function"]["name"], "read_file")
        self.assertEqual(call["function"]["arguments"], {"path": "README.md"})

    def test_rejects_wrappers_extra_fields_and_wrong_types(self) -> None:
        invalid = [
            "```json\n{}\n```",
            '{"name":"read_file","arguments":{},"explanation":"trust me"}',
            '{"name":7,"arguments":{}}',
            '{"name":"read_file","arguments":[]}',
        ]

        for content in invalid:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_content_tool_call(content)


if __name__ == "__main__":
    unittest.main()
