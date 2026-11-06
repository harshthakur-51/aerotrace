"""Generate the first three-case experiment and descriptive summaries."""

from dataclasses import asdict
import csv
import json
import math
from pathlib import Path
import statistics

from .plant import Observation, Parameters, Scenario, simulate


def run_experiment(output: Path, seed: int = 7, parameters: Parameters | None = None) -> dict:
    """Write an experiment to a NEW folder, preserving existing runs.

    Summaries use the known injection time for offline inspection. They are not
    diagnostic results, fault-classification accuracy, or benchmark statistics.
    """
    parameters = parameters or Parameters()
    if parameters.duration_s <= parameters.fault_time_s + 10:
        raise ValueError("This experiment needs more than 10 seconds after fault onset for its summary window")
    output.mkdir(parents=True, exist_ok=False)
    summary = {
        "experiment": "hydraulic-first-slice",
        "kind": "descriptive simulation checks; no diagnostic engine yet",
        "parameters": asdict(parameters),
        "seed": seed,
        "runs": [],
    }

    for number, scenario in enumerate(Scenario, start=1):
        run_id = f"run{number:03d}"
        run_dir = output / run_id
        truth_dir = run_dir / "private_truth"
        truth_dir.mkdir(parents=True)
        observations = []
        with (
            (run_dir / "telemetry.csv").open("w", newline="", encoding="utf-8") as telemetry_file,
            (truth_dir / "states.jsonl").open("w", encoding="utf-8") as truth_file,
        ):
            writer = csv.DictWriter(telemetry_file, fieldnames=list(Observation.__dataclass_fields__))
            writer.writeheader()
            for observation, truth in simulate(scenario, parameters, seed):
                writer.writerow(asdict(observation))
                truth_file.write(json.dumps(asdict(truth), allow_nan=False) + "\n")
                observations.append(observation)

        manifest = {"scenario": scenario.value, "seed": seed, "parameters": asdict(parameters)}
        (truth_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
        settled = [row for row in observations if row.t_s >= parameters.fault_time_s + 10]
        run_summary = {
            "run_id": run_id,
            "scenario": scenario.value,
            "sample_count": len(observations),
            "mean_measured_pressure_after_settling_bar": statistics.mean(
                row.hyd_b_pressure_bar for row in settled
            ),
            "final_measured_reservoir_l": observations[-1].hyd_b_reservoir_l,
            "tracking_error_rms_after_settling_deg": math.sqrt(statistics.mean(
                (row.actuator_command_deg - row.actuator_position_deg) ** 2 for row in settled
            )),
        }
        summary["runs"].append(run_summary)

    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8", newline="\n")
    return summary


def plot_experiment(output: Path) -> Path:
    """Plot observable channels only; labels and onset belong to offline analysis."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    labels = {
        "healthy": "Healthy",
        "hydraulic_leak": "Physical leak",
        "pressure_sensor_bias": "Pressure-sensor bias",
    }
    colors = ["#2563eb", "#dc573a", "#8a46bc"]
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    fig.patch.set_facecolor("#f7f8fb")
    pressure_values = []
    for run, color in zip(summary["runs"], colors):
        with (output / run["run_id"] / "telemetry.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        times = [float(row["t_s"]) for row in rows]
        channels = (
            [float(row["hyd_b_pressure_bar"]) for row in rows],
            [float(row["hyd_b_reservoir_l"]) for row in rows],
            [abs(float(row["actuator_command_deg"]) - float(row["actuator_position_deg"])) for row in rows],
        )
        pressure_values.extend(channels[0])
        for axis, values in zip(axes, channels):
            axis.plot(times, values, color=color, lw=1.45, alpha=0.85, label=labels[run["scenario"]])
    for axis, ylabel in zip(axes, ("Measured pressure (bar)", "Measured reservoir (L)", "Tracking error (deg)")):
        axis.axvline(summary["parameters"]["fault_time_s"], color="#596477", ls="--", lw=1)
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.15)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].legend(loc="upper right", ncol=3, fontsize=9)
    pressure_span = max(max(pressure_values) - min(pressure_values), 1.0)
    axes[0].set_ylim(min(pressure_values) - 0.1 * pressure_span, max(pressure_values) + 0.25 * pressure_span)
    fault_time = summary["parameters"]["fault_time_s"]
    axes[0].text(0.02, 0.94, f"Fault injected at {fault_time:g} s", transform=axes[0].transAxes, va="top", fontsize=9, color="#485366")
    axes[-1].set_xlabel("Simulation time (seconds)")
    axes[-1].set_xlim(0, summary["parameters"]["duration_s"])
    fig.suptitle("First experiment: low pressure can have different causes", x=0.1, ha="left", fontsize=16, weight="bold")
    telemetry_hz = 1.0 / summary["parameters"]["dt_s"]
    noise_fields = ("pressure_noise_sd_bar", "reservoir_noise_sd_l", "position_noise_sd_deg")
    noise_note = "noise disabled" if all(summary["parameters"][key] == 0 for key in noise_fields) else "same measurement-noise seed"
    fig.text(0.1, 0.925, f"Illustrative hydraulic plant | {telemetry_hz:g} Hz | {noise_note} | no diagnosis implemented", fontsize=9, color="#485366")
    fig.text(0.1, 0.025, "Leak drains fluid. Actuator effects depend on demand. Sensor bias affects only the reported pressure.", fontsize=9)
    fig.tight_layout(rect=(0.015, 0.045, 0.995, 0.91))
    target = output / "comparison.png"
    fig.savefig(target, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return target
