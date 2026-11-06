"""An illustrative hydraulic plant, not an aircraft-specific hydraulic model.

The forward plant owns the fault. Observations expose measurements only.
Pressure, reservoir quantity and actuator position are separate state variables.
"""

from dataclasses import dataclass
from enum import StrEnum
import math
import random
from typing import Iterator


class Scenario(StrEnum):
    HEALTHY = "healthy"
    LEAK = "hydraulic_leak"
    SENSOR_BIAS = "pressure_sensor_bias"


@dataclass(frozen=True)
class Parameters:
    dt_s: float = 0.05
    duration_s: float = 90.0
    fault_time_s: float = 20.0
    nominal_pressure_bar: float = 210.0
    initial_reservoir_l: float = 10.0
    pump_capacity_l_s: float = 0.25
    leak_coefficient_l_s: float = 0.10
    pressure_time_constant_s: float = 1.20
    sensor_bias_bar: float = -70.0
    pressure_noise_sd_bar: float = 0.6
    reservoir_noise_sd_l: float = 0.01
    position_noise_sd_deg: float = 0.02
    actuator_amplitude_deg: float = 15.0
    actuator_frequency_hz: float = 0.12

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        positive = (
            "dt_s", "duration_s", "nominal_pressure_bar", "initial_reservoir_l",
            "pump_capacity_l_s", "pressure_time_constant_s",
        )
        if any(getattr(self, name) <= 0 for name in positive):
            raise ValueError("Time steps, durations, capacities and time constants must be positive")
        nonnegative = (
            "leak_coefficient_l_s", "pressure_noise_sd_bar",
            "reservoir_noise_sd_l", "position_noise_sd_deg",
            "actuator_amplitude_deg", "actuator_frequency_hz",
        )
        if any(getattr(self, name) < 0 for name in nonnegative):
            raise ValueError("Leak, noise and actuator-demand parameters must be nonnegative")
        if self.dt_s > 0.05:
            raise ValueError("Use dt_s <= 0.05 for the actuator integration")
        if not 0 <= self.fault_time_s < self.duration_s:
            raise ValueError("Fault time must fall inside the episode")
        steps = self.duration_s / self.dt_s
        if not math.isclose(steps, round(steps), abs_tol=1e-8, rel_tol=0):
            raise ValueError("duration_s must be a whole number of time steps")


@dataclass(frozen=True)
class Observation:
    schema_version: int
    sequence: int
    t_s: float
    hyd_b_pressure_bar: float
    hyd_b_reservoir_l: float
    actuator_command_deg: float
    actuator_position_deg: float
    quality: str = "valid"


@dataclass(frozen=True)
class Truth:
    t_s: float
    active_fault: str
    pressure_bar: float
    reservoir_l: float
    actuator_position_deg: float
    external_leak_l_s: float


def _clip(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def simulate(
    scenario: Scenario,
    parameters: Parameters | None = None,
    seed: int = 7,
) -> Iterator[tuple[Observation, Truth]]:
    """Yield measurements and a separate evaluator-only truth record at 20 Hz.

    The pressure closure is intentionally low order: leakage reduces the target
    pressure, which is reached with a first-order response. It is not a detailed
    pressure/flow network. External leakage drains the reservoir; pump circulation
    is assumed to return to it. Sensor bias changes no physical state.
    """
    scenario = Scenario(scenario)
    p = parameters or Parameters()
    rng = random.Random(seed)
    pressure = p.nominal_pressure_bar
    reservoir = p.initial_reservoir_l
    position = 0.0
    steps = round(p.duration_s / p.dt_s)

    for index in range(steps + 1):
        t = index * p.dt_s
        active = scenario != Scenario.HEALTHY and t >= p.fault_time_s
        command = p.actuator_amplitude_deg * math.sin(2.0 * math.pi * p.actuator_frequency_hz * t)
        coefficient = p.leak_coefficient_l_s if active and scenario == Scenario.LEAK else 0.0
        leak = coefficient * math.sqrt(max(0.0, pressure / p.nominal_pressure_bar))
        leak = min(leak, reservoir / p.dt_s)
        bias = p.sensor_bias_bar if active and scenario == Scenario.SENSOR_BIAS else 0.0

        observation = Observation(
            schema_version=1,
            sequence=index,
            t_s=t,
            hyd_b_pressure_bar=max(0.0, pressure + bias + rng.gauss(0, p.pressure_noise_sd_bar)),
            hyd_b_reservoir_l=max(0.0, reservoir + rng.gauss(0, p.reservoir_noise_sd_l)),
            actuator_command_deg=command,
            actuator_position_deg=position + rng.gauss(0, p.position_noise_sd_deg),
        )
        truth = Truth(
            t_s=t,
            active_fault=scenario.value if active else "none",
            pressure_bar=pressure,
            reservoir_l=reservoir,
            actuator_position_deg=position,
            external_leak_l_s=leak,
        )
        yield observation, truth
        if index == steps:
            return

        # An illustrative loaded actuator: weaker pressure increases lag and
        # limits movement rate. It receives the command, never the sensor reading.
        pressure_fraction = _clip(pressure / p.nominal_pressure_bar, 0.0, 1.0)
        actuator_tau = 0.15 / max(pressure_fraction, 0.05) ** 2
        max_rate = 20.0 * pressure_fraction
        rate = _clip((command - position) / actuator_tau, -max_rate, max_rate)
        position += rate * p.dt_s

        reservoir = max(0.0, reservoir - leak * p.dt_s)
        pump_head = _clip(reservoir / 2.0, 0.0, 1.0)
        flow_margin = _clip(1.0 - leak / p.pump_capacity_l_s, 0.0, 1.0)
        target_pressure = p.nominal_pressure_bar * pump_head * flow_margin
        response = 1.0 - math.exp(-p.dt_s / p.pressure_time_constant_s)
        pressure += (target_pressure - pressure) * response
