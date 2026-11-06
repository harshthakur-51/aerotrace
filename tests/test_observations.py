"""Public observation schemas reject truth leakage and corrupted replay input."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aircraft_debugger.flightgear import PropertyReading, TelemetrySnapshot
from aircraft_debugger.observations import (
    CHANNELS, ObservationFormatError, iter_observations, observation_record,
    validate_observation, write_observation,
)


def snapshot(at=101.0):
    readings = {}
    for name, spec in CHANNELS.items():
        value = "A320-200-CFM" if spec.kind == "string" else False if spec.kind == "bool" else 42.0
        readings[name] = PropertyReading(spec.path, value, True, None, 10.0, at, True, spec.unit)
    return TelemetrySnapshot(readings, True, True, at + 0.1)


def record(index=0, at=101.0):
    return observation_record(snapshot(at), index, at - 0.1)


class ObservationTests(unittest.TestCase):
    def temporary_directory(self):
        # The project's tests must keep scratch files on the active Z: drive.
        base = Path(os.environ.get("AIRCRAFT_DEBUGGER_TEST_TMP", "Z:/aircraft-debugger/work/tests"))
        base.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def write_raw(self, rows):
        path = self.temporary_directory() / "observations.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return path

    def test_round_trip_preserves_non_atomic_readings_and_replay_uses_only_named_file(self):
        first = record()
        first["readings"]["altitude"]["received_monotonic_s"] = 100.95
        first["readings"]["altitude"]["sim_time_s"] = 9.5
        second = record(index=3, at=102.0)
        # A simulator reset is valid input that the evidence analyzer must guard.
        second["readings"]["sim_time"]["value"] = 0.1
        path = self.temporary_directory() / "observations.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            write_observation(stream, first)
            write_observation(stream, second)
        original_open = Path.open
        opened = []

        def tracked_open(target, *args, **kwargs):
            opened.append(target)
            return original_open(target, *args, **kwargs)

        with patch.object(Path, "open", tracked_open):
            restored = list(iter_observations(path))
        self.assertEqual(restored, [first, second])
        self.assertEqual(opened, [path])

    def test_missing_and_invalid_channels_are_visible_without_zero_fill(self):
        missing = record()
        del missing["readings"]["blue_pressure"]
        missing["complete"] = False
        self.assertIs(validate_observation(missing), missing)
        invalid = record()
        invalid["complete"] = False
        invalid["readings"]["blue_pressure"].update(
            value=None, valid=False, error="missing_property", sim_time_s=None
        )
        self.assertIsNone(validate_observation(invalid)["readings"]["blue_pressure"]["value"])
        invalid["readings"]["blue_pressure"]["value"] = 0
        with self.assertRaisesRegex(ObservationFormatError, "value=null"):
            validate_observation(invalid)

    def test_disconnection_retains_unavailability_and_strict_flag_meanings(self):
        disconnected = record()
        disconnected.update(connected=False, complete=False)
        for reading in disconnected["readings"].values():
            reading.update(value=None, valid=False, error="connection_error", sim_time_s=None, reachable=False)
        validate_observation(disconnected)
        disconnected["connected"] = True
        with self.assertRaisesRegex(ObservationFormatError, "connected must match"):
            validate_observation(disconnected)
        missing = record()
        del missing["readings"]["blue_pressure"]
        with self.assertRaisesRegex(ObservationFormatError, "complete"):
            validate_observation(missing)

    def test_private_fields_aliases_paths_units_and_error_labels_are_rejected_before_write(self):
        cases = []
        changed = record()
        changed["fault"] = "blue_leak"
        cases.append(changed)
        changed = record()
        changed["readings"]["root_cause"] = changed["readings"]["paused"].copy()
        cases.append(changed)
        changed = record()
        changed["readings"]["paused"]["path"] = "/systems/failures/hydraulic/blue-leak"
        cases.append(changed)
        changed = record()
        changed["readings"]["blue_pressure"]["unit"] = "blue_leak"
        cases.append(changed)
        changed = record()
        changed["readings"]["blue_pressure"]["label"] = "blue_leak"
        cases.append(changed)
        changed = record()
        changed["complete"] = False
        changed["readings"]["blue_pressure"].update(value=None, valid=False, sim_time_s=None, error="fault=blue_leak")
        cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed):
                stream = io.StringIO()
                with self.assertRaises(ObservationFormatError):
                    write_observation(stream, changed)
                self.assertEqual(stream.getvalue(), "")

    def test_typed_finite_values_and_timestamps_are_required(self):
        cases = [
            ("sample_index", True), ("sample_index", -1), ("schema_version", True),
            ("connected", 1), ("poll_started_monotonic_s", float("nan")),
            ("received_monotonic_s", float("inf")),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                changed = record()
                changed[field] = value
                with self.assertRaises(ObservationFormatError):
                    validate_observation(changed)
        for name, value in (("altitude", True), ("altitude", "42"), ("altitude", float("nan")),
                            ("paused", 0), ("aircraft", 42)):
            with self.subTest(name=name, value=value):
                changed = record()
                changed["readings"][name]["value"] = value
                with self.assertRaises(ObservationFormatError):
                    validate_observation(changed)
        changed = record()
        changed["readings"]["altitude"]["received_monotonic_s"] = 100.0
        with self.assertRaisesRegex(ObservationFormatError, "within this poll"):
            validate_observation(changed)

    def test_replay_rejects_index_and_local_time_regression_with_line_context(self):
        for second in (record(index=0, at=102), record(index=1, at=100)):
            with self.subTest(second=second):
                path = self.write_raw([record(), second])
                with self.assertRaisesRegex(ObservationFormatError, r"line 2:.*(increase strictly|moved backwards)"):
                    list(iter_observations(path))
        # End-of-poll time can increase even when one channel regresses.
        first = record()
        first["readings"]["altitude"]["received_monotonic_s"] = 101.05
        second = record(index=1, at=101.0)
        second["received_monotonic_s"] = 101.2
        path = self.write_raw([first, second])
        with self.assertRaisesRegex(ObservationFormatError, r"line 2: readings.altitude.*moved backwards"):
            list(iter_observations(path))

    def test_malformed_duplicate_and_nonfinite_json_have_actionable_line_errors(self):
        valid = json.dumps(record())
        malformed = ["{", "", valid[:-1] + ',"sample_index":1}', valid.replace('"value": 42.0', '"value": NaN', 1)]
        for line in malformed:
            with self.subTest(line=line[:80]):
                path = self.temporary_directory() / "bad.jsonl"
                path.write_text(valid + "\n" + line + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ObservationFormatError, "line 2:"):
                    list(iter_observations(path))
        path = self.temporary_directory() / "invalid-utf8.jsonl"
        path.write_bytes(valid.encode("utf-8") + b"\n\xff\n")
        with self.assertRaisesRegex(ObservationFormatError, "line 2:"):
            list(iter_observations(path))


if __name__ == "__main__":
    unittest.main()
