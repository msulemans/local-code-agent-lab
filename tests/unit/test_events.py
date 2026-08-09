from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import unittest

from localcode.events import Event, EventError, EventType


def sample_event() -> Event:
    return Event(
        schema_version=1,
        run_id="run-0001",
        sequence=0,
        timestamp="2026-08-08T09:00:00+10:00",
        event_type=EventType.RUN_CREATED,
        state="created",
        summary="Run contract created without executing tools.",
        artifact_refs=("artifacts/config.json",),
        budgets_remaining=(("steps", 12), ("tokens", 4096)),
    )


class EventTests(unittest.TestCase):
    def test_event_round_trips_through_json_exactly(self) -> None:
        original = sample_event()

        restored = Event.from_json(original.to_json())

        self.assertEqual(restored, original)

    def test_event_is_immutable(self) -> None:
        event = sample_event()

        with self.assertRaises(FrozenInstanceError):
            event.summary = "changed"  # type: ignore[misc]

    def test_mutable_collections_are_rejected(self) -> None:
        with self.assertRaisesRegex(EventError, "immutable tuple"):
            Event(
                schema_version=1,
                run_id="run-0001",
                sequence=0,
                timestamp="2026-08-08T09:00:00+10:00",
                event_type=EventType.NOTE,
                state="created",
                summary="Mutable artifacts are not allowed.",
                artifact_refs=["artifact.json"],  # type: ignore[arg-type]
            )

    def test_unknown_event_field_is_rejected(self) -> None:
        values = sample_event().to_dict()
        values["unexpected"] = True

        with self.assertRaisesRegex(EventError, "unknown event fields"):
            Event.from_dict(values)

    def test_negative_budget_is_rejected(self) -> None:
        with self.assertRaisesRegex(EventError, "non-negative integer"):
            Event(
                schema_version=1,
                run_id="run-0001",
                sequence=0,
                timestamp="2026-08-08T09:00:00+10:00",
                event_type=EventType.NOTE,
                state="created",
                summary="Invalid budget example.",
                budgets_remaining=(("steps", -1),),
            )

    def test_budget_names_must_be_canonical(self) -> None:
        with self.assertRaisesRegex(EventError, "sorted by budget name"):
            Event(
                schema_version=1,
                run_id="run-0001",
                sequence=0,
                timestamp="2026-08-08T09:00:00+10:00",
                event_type=EventType.NOTE,
                state="created",
                summary="Unsorted budget example.",
                budgets_remaining=(("tokens", 100), ("steps", 2)),
            )

    def test_serialized_json_is_canonical(self) -> None:
        payload = sample_event().to_json()

        self.assertEqual(payload, json.dumps(json.loads(payload), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    unittest.main()
