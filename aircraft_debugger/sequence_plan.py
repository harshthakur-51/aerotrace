"""Generate a private design of fault onsets and releases for later collection."""

import argparse
import json
from pathlib import Path

from .onset_orders import ordered_onsets


FAULTS = ("generator_2", "blue_leak", "blue_pump", "engine_2_cutoff", "yellow_edp")


def onset_groups(remaining=FAULTS):
    """Enumerate ordered, nonempty onset groups, with each selected fault used once."""
    yield from ordered_onsets(remaining)


def make_plan(*, hold_s=28, overlap_spacing_s=8, clear_gap_s=10):
    """Produce planned command offsets for overlapping and clear-gap variants."""
    if any(type(value) is not int or not 1 <= value <= 60
           for value in (hold_s, overlap_spacing_s, clear_gap_s)):
        raise ValueError("Timing settings must be whole simulator seconds from 1 to 60")
    if overlap_spacing_s >= hold_s:
        raise ValueError("Overlap spacing must be shorter than the hold time")
    sequences = list(onset_groups())
    trials = []
    for groups in sequences:
        timings = (("single_onset", hold_s),)
        if len(groups) > 1:
            timings = (("overlap", overlap_spacing_s), ("clear_gap", hold_s + clear_gap_s))
        for label, spacing_s in timings:
            trials.append({
                "timing": label,
                "onsets": [
                    {"faults": list(group), "enable_offset_sim_s": index * spacing_s,
                     "release_offset_sim_s": index * spacing_s + hold_s}
                    for index, group in enumerate(groups)
                ],
            })
    return {
        "kind": "private operator design",
        "run_permission": "planning_only",
        "timing": {"hold_sim_s": hold_s, "overlap_spacing_sim_s": overlap_spacing_s,
                   "clear_gap_sim_s": clear_gap_s},
        "onset_order_count": len(sequences),
        "strict_order_count": sum(all(len(group) == 1 for group in groups) for groups in sequences),
        "trial_count": len(trials),
        "trials": trials,
        "scope": "One onset per selected fault. Release is a requested control action. Physical recovery and transition admission require observation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New private plan JSON file")
    parser.add_argument("--hold-seconds", type=int, default=28)
    parser.add_argument("--overlap-spacing-seconds", type=int, default=8)
    parser.add_argument("--clear-gap-seconds", type=int, default=10)
    args = parser.parse_args()
    try:
        plan = make_plan(hold_s=args.hold_seconds, overlap_spacing_s=args.overlap_spacing_seconds,
                         clear_gap_s=args.clear_gap_seconds)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(plan, output, indent=2)
        output.write("\n")
    print(f"{plan['onset_order_count']} onset orders, {plan['trial_count']} planned timing variants")


if __name__ == "__main__":
    main()
