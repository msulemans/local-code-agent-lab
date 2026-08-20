from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from localcode.model_pin import ModelPinError, verify_model_pin


class ModelPinTests(unittest.TestCase):
    def test_exact_snapshot_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "models/example"
            model.mkdir(parents=True)
            (model / "weights.bin").write_bytes(b"weights")
            self.assertEqual(
                verify_model_pin(_document(hashlib.sha256(b"weights").hexdigest()), project_root=root),
                model.resolve(),
            )

    def test_tampering_and_path_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "models/example"
            model.mkdir(parents=True)
            (model / "weights.bin").write_bytes(b"tampered")
            with self.assertRaisesRegex(ModelPinError, "byte count mismatch"):
                verify_model_pin(_document("0" * 64), project_root=root)
            document = _document("0" * 64)
            document["snapshot_path"] = "../outside"
            with self.assertRaisesRegex(ModelPinError, "relative and canonical"):
                verify_model_pin(document, project_root=root)


def _document(digest: str) -> dict[str, object]:
    return {
        "model_id": "example/model", "source_model_id": "example/source",
        "revision": "a" * 40, "snapshot_path": "models/example", "quantization_bits": 4,
        "total_pinned_bytes": 7,
        "files": [{"path": "weights.bin", "bytes": 7, "sha256": digest}],
    }


if __name__ == "__main__":
    unittest.main()
