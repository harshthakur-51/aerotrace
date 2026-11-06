"""Read-only qualification of one observed airborne experiment baseline.

The defaults are project experiment choices from docs/AIRBORNE-TEST-PROTOCOL.md,
not aircraft limits or a flightworthiness decision. Private initialization checks
are accepted separately from the public observation record and are never copied
into returned results. No simulator reads, writes or fault controls occur here.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import math

from .airborne_profile import (
    AIRBORNE_CHANNELS, PROFILE_ID, PROPULSION_CHANNELS, PROPULSION_PROFILE_ID,
    validate_airborne_observation, validate_propulsion_observation,
)
from .flightgear import PropertyReading, PropertySpec, TelemetrySnapshot


READINESS_CHANNELS = {
    "startup_in_progress": PropertySpec("/systems/acconfig/autoconfig-running", kind="bool"),
    "startup_mismatch_reason": PropertySpec("/systems/acconfig/mismatch-reason", kind="string"),
    "engine_1_running": PropertySpec("/engines/engine[0]/running", kind="bool"),
    "engine_2_running": PropertySpec("/engines/engine[1]/running", kind="bool"),
    "generator_2_fault": PropertySpec("/systems/failures/electrical/gen-2", kind="bool"),
    "blue_leak_fault": PropertySpec("/systems/failures/hydraulic/blue-leak", kind="bool"),
    "blue_pump_fault": PropertySpec("/systems/failures/hydraulic/blue-elec", kind="bool"),
}
_READINESS_SPECS = dict(READINESS_CHANNELS)
_EXPECTED_READINESS = {
    "startup_in_progress": False, "startup_mismatch_reason": "XX", "engine_1_running": True, "engine_2_running": True,
    "generator_2_fault": False, "blue_leak_fault": False,
    "blue_pump_fault": False,
}
PROPULSION_FAULTS = {
    "engine_2_cutoff": "/controls/engines/engine[1]/cutoff-switch",
    "yellow_edp": "/systems/failures/hydraulic/yellow-edp",
}
PROPULSION_READINESS_CHANNELS = {
    **_READINESS_SPECS,
    **{f"{name}_fault": PropertySpec(path, kind="bool") for name, path in PROPULSION_FAULTS.items()},
}
_PROPULSION_REFERENCE_MINIMA = {
    "engine_2_n2": 60.0, "engine_2_fuel_flow": 100.0, "yellow_edp_pressure": 2500.0,
    "yellow_pressure": 2500.0, "yellow_quantity": 1.0,
}


def _number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class QualificationSettings:
    altitude_target_ft: float = 10000.0
    altitude_tolerance_ft: float = 200.0
    airspeed_target_kt: float = 250.0
    airspeed_tolerance_kt: float = 10.0
    minimum_height_agl_ft: float = 3000.0
    maximum_abs_bank_deg: float = 5.0
    maximum_abs_vertical_speed_fps: float = 5.0
    qualification_duration_sim_s: float = 15.0
    maximum_sim_gap_s: float = 3.0
    maximum_local_gap_s: float = 3.0
    maximum_reading_age_s: float = 2.0
    maximum_poll_span_s: float = 2.0
    maximum_timestamp_skew_s: float = 2.0
    minimum_reference_voltage_v: float = 100.0
    minimum_blue_quantity_raw: float = 7.9
    minimum_blue_pressure_psi: float = 2500.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not _number(value) or value < 0:
                raise ValueError(f"{field.name} must be a finite nonnegative number, not a boolean")
        positive = ("airspeed_target_kt", "minimum_height_agl_ft", "qualification_duration_sim_s",
                    "maximum_sim_gap_s", "maximum_local_gap_s", "maximum_reading_age_s",
                    "maximum_poll_span_s", "maximum_timestamp_skew_s", "minimum_reference_voltage_v",
                    "minimum_blue_quantity_raw", "minimum_blue_pressure_psi")
        if any(getattr(self, name) <= 0 for name in positive):
            raise ValueError("Duration, timing bounds, speed and reference minima must be positive")
        if self.airspeed_tolerance_kt >= self.airspeed_target_kt or self.maximum_abs_bank_deg > 180:
            raise ValueError("Airspeed tolerance must be below its target; absolute bank bound cannot exceed 180 degrees")


class AirborneAdmission:
    """A non-latching gate for consecutive, observed pre-intervention samples.

    Qualification duration is the minimum advancement of every required reading's
    own simulator timestamp and the observed simulator clock. Local receipt times
    are used only for freshness, poll span and local gaps. A failed sample revokes
    qualification and clears the window. Automation changes also clear the window.
    This gate must not filter or discard post-intervention motion outcomes.
    """

    def __init__(self, settings: QualificationSettings | None = None, *, ptu_selected: bool | None = None):
        if settings is not None and not isinstance(settings, QualificationSettings):
            raise TypeError("settings must be QualificationSettings or None")
        self.settings = settings or QualificationSettings()
        if ptu_selected is not None and type(ptu_selected) is not bool:
            raise TypeError("ptu_selected must be Boolean or None")
        self.ptu_selected = ptu_selected
        self.channels = AIRBORNE_CHANNELS if ptu_selected is None else PROPULSION_CHANNELS
        self.readiness_channels = _READINESS_SPECS if ptu_selected is None else PROPULSION_READINESS_CHANNELS
        self._previous_index: int | None = None
        self._previous_local: float | None = None
        self._previous_evaluation: float | None = None
        self._previous_channel_sim: dict[str, float] = {}
        self._previous_channel_local: dict[str, float] = {}
        self._previous_automation: tuple[bool, bool, bool] | None = None
        self._window_start: dict | None = None
        self._window_channel_start: dict[str, float] = {}

    def _clear_window(self) -> None:
        self._window_start = None
        self._window_channel_start.clear()

    def _result(self, reasons: list[str], sample: dict | None = None, elapsed: float = 0.0) -> dict:
        eligible = not reasons
        qualified = eligible and elapsed >= self.settings.qualification_duration_sim_s
        return {
            "profile_id": PROFILE_ID if self.ptu_selected is None else PROPULSION_PROFILE_ID,
            "purpose": "experiment_baseline_eligibility_only",
            "qualified": qualified, "eligible_current_sample": eligible,
            "reasons": list(dict.fromkeys(reasons)) if reasons else [] if qualified else ["qualification_window_incomplete"],
            "window_elapsed_sim_s": elapsed if eligible else 0.0,
            "window_start": dict(self._window_start) if eligible and self._window_start else None,
            "window_end": dict(sample) if eligible and sample else None,
        }

    def update(self, record: dict, readiness: TelemetrySnapshot, evaluated_monotonic_s: float) -> dict:
        """Evaluate data only; malformed/missing inputs fail closed with generic reasons."""
        if not _number(evaluated_monotonic_s) or evaluated_monotonic_s < 0:
            self._clear_window()
            return self._result(["evaluation_clock_invalid"])
        try:
            validator = validate_airborne_observation if self.ptu_selected is None else validate_propulsion_observation
            record = validator(record)
        except (ValueError, TypeError, KeyError):
            self._clear_window()
            return self._result(["observation_contract_invalid"])
        settings = self.settings
        reasons: list[str] = []
        readings = record["readings"]
        index, local = record["sample_index"], record["received_monotonic_s"]
        if record["connected"] is not True or record["complete"] is not True or readings.keys() != self.channels.keys():
            reasons.append("required_observations_unavailable")
        if local - record["poll_started_monotonic_s"] > settings.maximum_poll_span_s:
            reasons.append("observation_poll_span_exceeded")
        if local > evaluated_monotonic_s:
            reasons.append("observation_clock_invalid")
        if self._previous_index is not None:
            if index <= self._previous_index:
                reasons.append("sample_index_not_advancing")
            elif index != self._previous_index + 1:
                reasons.append("sample_index_gap")
        if self._previous_local is not None:
            if local <= self._previous_local:
                reasons.append("local_clock_not_advancing")
            elif local - self._previous_local > settings.maximum_local_gap_s:
                reasons.append("local_sample_gap_exceeded")
        if self._previous_evaluation is not None:
            if evaluated_monotonic_s <= self._previous_evaluation:
                reasons.append("evaluation_clock_not_advancing")
            elif evaluated_monotonic_s - self._previous_evaluation > settings.maximum_local_gap_s:
                reasons.append("evaluation_gap_exceeded")

        sim_times, local_times = {}, {}
        values = {}
        for name in self.channels:
            reading = readings.get(name)
            if not reading or reading["valid"] is not True or reading["reachable"] is not True:
                reasons.append("required_observations_unavailable")
                continue
            values[name] = reading["value"]
            if not _number(reading["sim_time_s"]) or reading["sim_time_s"] < 0:
                reasons.append("required_simulator_timestamp_unavailable")
                continue
            sim_times[name] = reading["sim_time_s"]
            local_times[name] = reading["received_monotonic_s"]

        valid_initialization = isinstance(readiness, TelemetrySnapshot)
        if valid_initialization:
            valid_initialization = readiness.connected is True and readiness.complete is True and isinstance(readiness.readings, dict) and readiness.readings.keys() == self.readiness_channels.keys() and _number(readiness.received_monotonic_s) and readiness.received_monotonic_s >= 0
        if valid_initialization:
            initialization_receipts = []
            for name, spec in self.readiness_channels.items():
                reading = readiness.readings[name]
                typed = isinstance(reading, PropertyReading) and (type(reading.value) is bool if spec.kind == "bool" else isinstance(reading.value, str))
                valid = typed and reading.path == spec.path and reading.unit == spec.unit and reading.valid is True and reading.reachable is True and reading.error is None and _number(reading.sim_time_s) and reading.sim_time_s >= 0 and _number(reading.received_monotonic_s) and 0 <= reading.received_monotonic_s <= readiness.received_monotonic_s
                if not valid:
                    valid_initialization = False
                    continue
                if reading.value != _EXPECTED_READINESS.get(name, False):
                    reasons.append("initialization_reference_not_ready")
                # Internal names are never copied into returned eligibility results.
                sim_times["initialization:" + name] = reading.sim_time_s
                local_times["initialization:" + name] = reading.received_monotonic_s
                initialization_receipts.append(reading.received_monotonic_s)
            if initialization_receipts and readiness.received_monotonic_s - min(initialization_receipts) > settings.maximum_poll_span_s:
                reasons.append("initialization_check_span_exceeded")
            if readiness.received_monotonic_s > evaluated_monotonic_s:
                reasons.append("initialization_check_clock_invalid")
        if not valid_initialization:
            reasons.append("initialization_check_unavailable")

        for name, timestamp in sim_times.items():
            if name in self._previous_channel_sim:
                difference = timestamp - self._previous_channel_sim[name]
                if difference <= 0:
                    reasons.append("required_channel_time_not_advancing")
                elif difference > settings.maximum_sim_gap_s:
                    reasons.append("required_simulator_gap_exceeded")
        for name, timestamp in local_times.items():
            age = evaluated_monotonic_s - timestamp
            if age < 0 or age > settings.maximum_reading_age_s:
                reasons.append("required_observation_not_fresh")
            if name in self._previous_channel_local:
                difference = timestamp - self._previous_channel_local[name]
                if difference <= 0:
                    reasons.append("required_receipt_clock_not_advancing")
                elif difference > settings.maximum_local_gap_s:
                    reasons.append("required_local_gap_exceeded")
        if values:
            if values.get("aircraft") != "A320-200-CFM":
                reasons.append("pinned_aircraft_not_observed")
            if values.get("paused") is not False:
                reasons.append("simulator_not_confirmed_unpaused")
            clock = values.get("sim_time")
            if _number(clock) and clock >= 0:
                previous_clock = self._previous_channel_sim.get("observed_clock")
                if previous_clock is not None and (clock <= previous_clock or clock - previous_clock > settings.maximum_sim_gap_s):
                    reasons.append("simulator_clock_discontinuity")
                sim_times["observed_clock"] = clock
            else:
                reasons.append("simulator_clock_invalid")
            required_values = ("altitude", "airspeed", "height_agl", "bank", "vertical_speed", "generator_2_voltage", "ac_bus_1", "ac_bus_2", "blue_quantity", "blue_pressure")
            if all(name in values for name in required_values):
                if abs(values["altitude"] - settings.altitude_target_ft) > settings.altitude_tolerance_ft:
                    reasons.append("altitude_outside_reference_band")
                if abs(values["airspeed"] - settings.airspeed_target_kt) > settings.airspeed_tolerance_kt:
                    reasons.append("airspeed_outside_reference_band")
                if values["height_agl"] < settings.minimum_height_agl_ft or values.get("main_gear_1_wow") is not False or values.get("main_gear_2_wow") is not False:
                    reasons.append("airborne_context_not_established")
                if abs(values["bank"]) > settings.maximum_abs_bank_deg or abs(values["vertical_speed"]) > settings.maximum_abs_vertical_speed_fps:
                    reasons.append("flight_context_outside_stability_band")
                if any(values[name] < settings.minimum_reference_voltage_v for name in ("generator_2_voltage", "ac_bus_1", "ac_bus_2")) or values["blue_quantity"] < settings.minimum_blue_quantity_raw or values["blue_pressure"] < settings.minimum_blue_pressure_psi:
                    reasons.append("observed_reference_supply_inadequate")
            if self.ptu_selected is not None:
                if (values.get("ptu_selected") is not self.ptu_selected
                        or any(values.get(name, 0) < minimum for name, minimum in _PROPULSION_REFERENCE_MINIMA.items())
                        or any(not 0 <= values.get(name, 500) < 500 for name in
                               ("yellow_electric_pressure", "yellow_transfer_pressure"))):
                    reasons.append("propulsion_reference_or_backup_configuration_invalid")
        if sim_times and max(sim_times.values()) - min(sim_times.values()) > settings.maximum_timestamp_skew_s:
            reasons.append("required_timestamp_skew_exceeded")
        automation = tuple(values.get(name) for name in ("autopilot_1", "autopilot_2", "autothrust"))
        if all(type(value) is bool for value in automation):
            if self._previous_automation is not None and automation != self._previous_automation:
                reasons.append("automation_context_changed")
            self._previous_automation = automation
        self._previous_index, self._previous_local = index, local
        self._previous_evaluation = evaluated_monotonic_s
        self._previous_channel_sim.update(sim_times)
        self._previous_channel_local.update(local_times)
        if reasons:
            self._clear_window()
            return self._result(reasons)
        sample = {"sample_index": index, "sim_time_s": values["sim_time"], "received_monotonic_s": local}
        if self._window_start is None:
            self._window_start = sample
            self._window_channel_start = dict(sim_times)
        elapsed = min(timestamp - self._window_channel_start[name] for name, timestamp in sim_times.items())
        return self._result([], sample, elapsed)
