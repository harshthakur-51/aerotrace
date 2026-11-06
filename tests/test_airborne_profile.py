"""Airborne recording boundaries, independent of any connected simulator."""

import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aircraft_debugger.airborne_profile import (
    AIRBORNE_CHANNELS, PROFILE_ID, airborne_observation_record,
    iter_profile_observations, validate_airborne_observation, write_airborne_observation,
)
from aircraft_debugger.evidence import analyze_observations
from aircraft_debugger.flightgear import PropertyReading, TelemetrySnapshot
from aircraft_debugger.observations import (
    CHANNELS, ObservationFormatError, iter_observations, observation_record, validate_observation,
)


def make_snapshot(*, airborne=True, at=101.0):
    specs = AIRBORNE_CHANNELS if airborne else CHANNELS
    readings = {}
    for name, spec in specs.items():
        value = "A320-200-CFM" if spec.kind == "string" else False if spec.kind == "bool" else 42.0
        readings[name] = PropertyReading(spec.path, value, True, None, at - 90, at, True, spec.unit)
    return TelemetrySnapshot(readings, True, True, at + 0.1)


def airborne_record(index=0, at=101.0):
    return airborne_observation_record(make_snapshot(at=at), index, at - 0.1)


def legacy_record(index=0, at=101.0):
    return observation_record(make_snapshot(airborne=False, at=at), index, at - 0.1)


class AirborneProfileTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("AIRCRAFT_DEBUGGER_TEST_TMP", "Z:/aircraft-debugger/work/tests"))
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def raw_file(self, rows):
        path = self.directory / "observations.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_exact_twenty_channel_allowlist_extends_without_mutating_legacy(self):
        self.assertEqual(len(CHANNELS), 12)
        self.assertEqual(len(AIRBORNE_CHANNELS), 20)
        self.assertEqual({name: AIRBORNE_CHANNELS[name] for name in CHANNELS}, CHANNELS)
        expected = {
            "main_gear_1_wow": ("/gear/gear[1]/wow", "bool", ""),
            "main_gear_2_wow": ("/gear/gear[2]/wow", "bool", ""),
            "height_agl": ("/position/altitude-agl-ft", "number", "ft"),
            "vertical_speed": ("/velocities/vertical-speed-fps", "number", "ft/s"),
            "bank": ("/orientation/roll-deg", "number", "deg"),
            "autopilot_1": ("/it-autoflight/output/ap1", "bool", ""),
            "autopilot_2": ("/it-autoflight/output/ap2", "bool", ""),
            "autothrust": ("/it-autoflight/output/athr", "bool", ""),
        }
        self.assertEqual(
            {name: (spec.path, spec.kind, spec.unit) for name, spec in AIRBORNE_CHANNELS.items() if name not in CHANNELS},
            expected,
        )

    def test_full_round_trip_retains_context_times_and_opens_only_explicit_file(self):
        first, second = airborne_record(), airborne_record(2, at=102)
        first["readings"]["bank"]["sim_time_s"] = 10.5
        first["readings"]["bank"]["received_monotonic_s"] = 100.95
        path = self.directory / "observations.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            write_airborne_observation(stream, first)
            write_airborne_observation(stream, second)
        original_open, opened = Path.open, []

        def tracked_open(target, *args, **kwargs):
            opened.append(target)
            return original_open(target, *args, **kwargs)

        with patch.object(Path, "open", tracked_open):
            restored = list(iter_profile_observations(path))
        self.assertEqual(restored, [first, second])
        self.assertEqual(opened, [path])
        self.assertEqual(restored[0]["observation_profile"], PROFILE_ID)

    def test_legacy_dispatch_preserves_exact_record_and_replay_identity(self):
        rows = [legacy_record(), legacy_record(1, at=102)]
        path = self.raw_file(rows)
        self.assertEqual(list(iter_profile_observations(path)), rows)
        self.assertEqual(list(iter_profile_observations(path)), list(iter_observations(path)))
        self.assertIs(validate_observation(rows[0]), rows[0])
        new_record = airborne_record()
        with self.assertRaises(ObservationFormatError):
            validate_observation(new_record)
        with self.assertRaises(ObservationFormatError):
            analyze_observations([new_record])

    def test_missing_or_invalid_context_is_never_complete_or_zero_filled(self):
        missing = airborne_record()
        del missing["readings"]["height_agl"]
        with self.assertRaisesRegex(ObservationFormatError, "all 20"):
            validate_airborne_observation(missing)
        missing["complete"] = False
        self.assertIs(validate_airborne_observation(missing), missing)
        invalid = airborne_record()
        invalid["complete"] = False
        invalid["readings"]["height_agl"].update(value=None, valid=False, error="missing_property", sim_time_s=None)
        self.assertIsNone(validate_airborne_observation(invalid)["readings"]["height_agl"]["value"])
        invalid["readings"]["height_agl"]["value"] = 0
        with self.assertRaisesRegex(ObservationFormatError, "value=null"):
            validate_airborne_observation(invalid)
        base_only = airborne_record()
        base_only["readings"] = {name: reading for name, reading in base_only["readings"].items() if name in CHANNELS}
        base_only["complete"] = False
        validate_airborne_observation(base_only)

    def test_private_extra_fields_aliases_paths_units_and_wrong_types_fail_before_write(self):
        cases = []
        changed = airborne_record()
        changed["fault"] = "blue_leak"
        cases.append(changed)
        changed = airborne_record()
        changed["observation_profile"] = "airborne-blue-leak"
        cases.append(changed)
        changed = airborne_record()
        changed["readings"]["fault_flag"] = changed["readings"]["main_gear_1_wow"].copy()
        cases.append(changed)
        changed = airborne_record()
        changed["readings"]["main_gear_1_wow"]["path"] = "/systems/failures/hydraulic/blue-leak"
        cases.append(changed)
        for name, field, value in (
            ("vertical_speed", "unit", "ft/min"), ("bank", "value", True),
            ("bank", "value", float("inf")), ("height_agl", "value", "4000"),
            ("autopilot_1", "value", 1), ("main_gear_1_wow", "valid", 1),
            ("bank", "received_monotonic_s", 99), ("bank", "sim_time_s", float("nan")),
        ):
            changed = airborne_record()
            changed["readings"][name][field] = value
            cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed):
                stream = io.StringIO()
                original = copy.deepcopy(changed)
                with self.assertRaises(ObservationFormatError):
                    write_airborne_observation(stream, changed)
                self.assertEqual(stream.getvalue(), "")
                # Validation must not turn the profile into a legacy record.
                self.assertEqual(changed["schema_version"], original["schema_version"])
                self.assertEqual(changed["observation_profile"], original["observation_profile"])

    def test_mixed_versions_profiles_and_nonmonotonic_sequences_are_rejected(self):
        for rows in (
            [legacy_record(), airborne_record(1, at=102)],
            [airborne_record(), legacy_record(1, at=102)],
            [airborne_record(), airborne_record(0, at=102)],
            [airborne_record(), airborne_record(1, at=100)],
        ):
            path = self.raw_file(rows)
            with self.subTest(rows=rows), self.assertRaisesRegex(ObservationFormatError, "line 2:"):
                list(iter_profile_observations(path))
        changed = airborne_record(1, at=102)
        changed["observation_profile"] = "unsupported-other-profile"
        with self.assertRaisesRegex(ObservationFormatError, "line 2:"):
            list(iter_profile_observations(self.raw_file([airborne_record(), changed])))
        first, second = airborne_record(), airborne_record(1)
        first["readings"]["bank"]["received_monotonic_s"] = 101.05
        second["received_monotonic_s"] = 101.2
        with self.assertRaisesRegex(ObservationFormatError, r"line 2: readings.bank.*backwards"):
            list(iter_profile_observations(self.raw_file([first, second])))

    def test_bounded_malformed_duplicate_and_nonfinite_json_errors_have_line_context(self):
        valid = json.dumps(airborne_record())
        corruptions = [b"{", b"", b"\xff", b"x" * 65_537,
                       (valid[:-1] + ',"sample_index":1}').encode(),
                       valid.replace('"value": 42.0', '"value": NaN', 1).encode()]
        for content in corruptions:
            with self.subTest(content=content[:40]):
                path = self.directory / "malformed.jsonl"
                path.write_bytes(valid.encode() + b"\n" + content + b"\n")
                with self.assertRaisesRegex(ObservationFormatError, "line 2:"):
                    list(iter_profile_observations(path))


if __name__ == "__main__":
    unittest.main()
