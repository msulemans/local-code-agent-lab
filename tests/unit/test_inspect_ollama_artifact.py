import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from inspect_ollama_artifact import inspect_artifact  # noqa: E402


class OllamaArtifactInspectionTests(unittest.TestCase):
    def create_artifact(
        self,
        root: Path,
        *,
        corrupt_blob: bool = False,
        manifest_size_delta: int = 0,
    ) -> tuple[str, str]:
        model = "example-coder:7b-q4_K_M"
        content = b"model weights"
        digest = hashlib.sha256(content).hexdigest()
        blob_directory = root / "blobs"
        blob_directory.mkdir(parents=True)
        (blob_directory / f"sha256-{digest}").write_bytes(b"corrupt" if corrupt_blob else content)

        manifest = {
            "schemaVersion": 2,
            "config": {
                "mediaType": "application/vnd.ollama.image.model",
                "digest": f"sha256:{digest}",
                "size": len(content) + manifest_size_delta,
            },
            "layers": [],
        }
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
        manifest_path = root / "manifests/registry.ollama.ai/library/example-coder/7b-q4_K_M"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_bytes(manifest_bytes)
        return model, hashlib.sha256(manifest_bytes).hexdigest()

    def test_verifies_manifest_and_every_referenced_blob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, manifest_sha256 = self.create_artifact(root)

            result = inspect_artifact(model, root)

            self.assertTrue(result["verified"])
            self.assertEqual(result["manifest_sha256"], manifest_sha256)
            self.assertEqual(result["blob_count"], 1)
            self.assertEqual(result["total_blob_bytes"], len(b"model weights"))
            self.assertTrue(result["hashes_verified"])
            self.assertTrue(result["descriptor_sizes_match"])

    def test_rejects_corrupted_blob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, _ = self.create_artifact(root, corrupt_blob=True)

            with self.assertRaisesRegex(ValueError, "blob hash mismatch"):
                inspect_artifact(model, root)

    def test_reports_authenticated_blob_with_incorrect_manifest_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, _ = self.create_artifact(root, manifest_size_delta=-3)

            result = inspect_artifact(model, root)

            self.assertTrue(result["hashes_verified"])
            self.assertFalse(result["descriptor_sizes_match"])
            self.assertEqual(result["size_mismatches"][0]["manifest_bytes"], 10)
            self.assertEqual(result["size_mismatches"][0]["actual_bytes"], 13)

    def test_rejects_unpinned_or_unsafe_model_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaisesRegex(ValueError, "name:tag"):
                inspect_artifact("latest", root)
            with self.assertRaisesRegex(ValueError, "only letters"):
                inspect_artifact("../escape:tag", root)


if __name__ == "__main__":
    unittest.main()
