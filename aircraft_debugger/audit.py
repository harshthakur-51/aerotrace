"""Session 1 input sweep for auditing the existing model, without changing its physics."""

import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path
import platform

from .experiment import run_experiment
from .plant import Parameters


def run_audit(output: Path) -> list[dict]:
    output.mkdir(parents=True, exist_ok=False)
    # Noise-free development experiments isolate assumptions; these are not a
    # robustness benchmark and the injection time is known only to offline analysis.
    base = Parameters(
        duration_s=60, fault_time_s=10,
        pressure_noise_sd_bar=0, reservoir_noise_sd_l=0, position_noise_sd_deg=0,
    )
    suites = {
        "small_leak_moving": replace(base, leak_coefficient_l_s=0.005),
        "larger_leak_moving": base,
        "larger_leak_stationary": replace(base, actuator_amplitude_deg=0),
    }
    rows = []
    for name, parameters in suites.items():
        summary = run_experiment(output / name, parameters=parameters)
        for run in summary["runs"]:
            rows.append({
                "suite": name,
                "run_id": run["run_id"],
                "scenario": run["scenario"],
                "leak_coefficient_l_s": parameters.leak_coefficient_l_s,
                "actuator_amplitude_deg": parameters.actuator_amplitude_deg,
                "mean_measured_pressure_bar": run["mean_measured_pressure_after_settling_bar"],
                "reservoir_loss_l": parameters.initial_reservoir_l - run["final_measured_reservoir_l"],
                "tracking_error_rms_deg": run["tracking_error_rms_after_settling_deg"],
            })
    with (output / "audit.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "purpose": "Model-assumption audit, not diagnostic evaluation",
        "physics": "Unchanged original pressure-target closure",
        "python": platform.python_version(),
        "noise": "Disabled for this audit",
        "episodes": len(rows),
        "summary_window": "fault onset + 10 seconds to episode end",
    }
    (output / "audit.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8", newline="\n")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="A new audit directory")
    args = parser.parse_args()
    try:
        rows = run_audit(args.output)
    except FileExistsError:
        parser.error("Audit directory already exists; choose a new name")
    for row in rows:
        print(
            f"{row['suite']} / {row['scenario']}: "
            f"pressure={row['mean_measured_pressure_bar']:.2f} bar, "
            f"fluid loss={row['reservoir_loss_l']:.3f} L, "
            f"tracking RMS={row['tracking_error_rms_deg']:.3f} deg"
        )


if __name__ == "__main__":
    main()
