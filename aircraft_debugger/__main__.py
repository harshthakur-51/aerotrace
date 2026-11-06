import argparse
import json
from pathlib import Path

from .experiment import plot_experiment, run_experiment
from .plant import Parameters


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the first Aircraft Debugger hydraulic experiment.")
    parser.add_argument("--output", type=Path, required=True, help="A new output directory")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--config", type=Path, help="JSON object overriding named model parameters")
    parser.add_argument("--plot", action="store_true", help="Also generate a comparison PNG (requires matplotlib)")
    args = parser.parse_args()
    try:
        overrides = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
        if not isinstance(overrides, dict):
            raise ValueError("Configuration must be a JSON object")
        parameters = Parameters(**overrides)
    except (OSError, TypeError, ValueError) as error:
        parser.error(f"Invalid model configuration: {error}")
    if args.plot:
        try:
            import matplotlib  # noqa: F401 -- check before creating experiment files
        except ImportError:
            parser.error("--plot needs matplotlib; install the optional plot dependency or omit --plot")
    try:
        summary = run_experiment(args.output, args.seed, parameters)
    except FileExistsError:
        parser.error("Output directory already exists; choose a new name to preserve existing results")
    except ValueError as error:
        parser.error(str(error))
    for run in summary["runs"]:
        print(
            f"{run['run_id']} {run['scenario']}: "
            f"pressure={run['mean_measured_pressure_after_settling_bar']:.1f} bar, "
            f"final reservoir={run['final_measured_reservoir_l']:.2f} L, "
            f"tracking RMS={run['tracking_error_rms_after_settling_deg']:.2f} deg"
        )
    if args.plot:
        print(f"Plot: {plot_experiment(args.output)}")
    print("These are descriptive simulator results, not diagnostic performance metrics.")


if __name__ == "__main__":
    main()
