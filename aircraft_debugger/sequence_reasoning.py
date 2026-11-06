"""Fit generated mechanism histories to public A320 observations."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from math import inf
from pathlib import Path

from .airborne_profile import PROPULSION_PROFILE_ID, iter_profile_observations, validate_airborne_observation
from .candidate_support import evidence_support
from .diagnosis import _sources, _write_json
from .diagnostic_features import build_feature_frames
from .hypotheses import _predictions, evaluate_hypotheses, generated_model
from .observations import _unique_object
from .onset_orders import ordered_onsets


_LOCAL_WITNESSES = {
    "generator_loss_with_drive_retained": ("generator_source_anomaly", "generator_2_voltage"),
    "yellow_pump_loss_with_drive_retained": ("yellow_edp_output_loss", "yellow_edp_pressure"),
}
_STATUSES = ("compatible", "unconfirmed", "excluded_by_dependency", "excluded_by_timing")
_SCOPE = [
    "Each selected mechanism has one onset per clock epoch. Groups permit a common onset time. Distinct groups require strict order.",
    "Required responses are assumed to be observable at least once within the replay for the represented sustained episodes.",
    "Response delays are nonnegative. A finite maximum is used only when declared for a required path and the first response has a covered normal reference.",
    "Each first observed effect needs at least one eligible upstream path. Overlapping paths can mask a later mechanism.",
    "Release times, repeated onsets, physical common origin and probabilities are outside the fitted model.",
]


def _response_bounds(bounds, model):
    if bounds is None:
        return {}
    if not isinstance(bounds, dict):
        raise ValueError("Response bounds must map mechanism IDs to dictionaries of effect bounds")
    _, paths = _predictions(model["roots"], model)
    allowed = {(path["nodes"][0], path["fact"]) for path in paths if path["necessity"] == "required"}
    result = {}
    for root, effects in bounds.items():
        if root not in model["roots"] or not isinstance(effects, dict) or not effects:
            raise ValueError(f"Unknown mechanism or empty effect bounds for {root}")
        for effect, interval in effects.items():
            if ((root, effect) not in allowed or not isinstance(interval, list) or len(interval) != 2
                    or any(type(value) not in (float, int) for value in interval)
                    or not 0 <= interval[0] <= interval[1] <= 120):
                raise ValueError(f"{root} / {effect} needs a required path and two ordered bounds in 0–120 simulator seconds")
        result[root] = {effect: list(interval) for effect, interval in effects.items()}
    return result


def _timing_constraints(frame, candidate, model, bounds):
    """Return onset floors and disjunctions of onset deadlines."""
    excluded_paths, witnesses, missing = set(), [], []
    roots = set(candidate["roots"])
    for rule in model["temporal_constraints"]:
        name, local = rule["id"], rule.get("unless_root")
        relation = frame["temporal_relations"].get(name, {})
        if not local or relation.get("status") != "contradicted":
            continue
        if name in _LOCAL_WITNESSES:
            effect, channel = _LOCAL_WITNESSES[name]
            if local not in roots:
                missing.append(name)
                continue
            time = min(point["sim_time_s"] for point in relation["evidence"] if point["channel"] == channel)
            minimum, _ = bounds.get(local, {}).get(effect, (0, inf))
            witnesses.append({"evidence_id": name, "latest_onset_sim_s": {local: time - minimum}})
        elif name == "inventory_before_pressure":
            # The inventory path cannot produce the first pressure loss here.
            # A different path can still explain it, and fluid loss can occur later.
            excluded_paths.add((rule["root"], "blue_pressure_loss"))

    floors, deadlines = [], []
    for consequence in candidate["predicted_consequences"]:
        effect = consequence["fact"]
        fact = frame["facts"][effect]
        if fact["state"] != "observed":
            continue
        onset = fact["onset_interval"]
        lower, upper = onset["lower_sim_time_s"], onset["upper_sim_time_s"]
        covered = onset["covered_through_confirmation"] and lower is not None and lower < upper
        sources = {}
        for path in consequence["dependency_paths"]:
            root = path["nodes"][0]
            if (root, effect) in excluded_paths:
                continue
            minimum, maximum = bounds.get(root, {}).get(effect, (0, inf))
            if covered and path["necessity"] == "required" and maximum < inf:
                floors.append({"root": root, "fact": effect, "earliest_onset_sim_s": lower - maximum})
            sources[root] = upper - minimum
        deadlines.append({"evidence_id": effect, "latest_onset_sim_s": sources})
    return {"onset_floors": floors, "deadlines": deadlines + witnesses, "missing_witness_paths": missing}


def _timing_conflict(groups, constraints):
    """Find an impossible deadline using the earliest feasible onset infima.

    Measurement bounds are inclusive. An earlier group at the same infimum
    makes the next group's lower endpoint open. All remaining constraints
    are upper deadlines, so moving any group later cannot improve a fit.
    """
    if constraints["missing_witness_paths"]:
        return {"missing_witness_paths": constraints["missing_witness_paths"]}
    root_floors = {root: -inf for group in groups for root in group}
    for item in constraints["onset_floors"]:
        root = item["root"]
        root_floors[root] = max(root_floors[root], item["earliest_onset_sim_s"])
    earliest = (-inf, False)
    infima = {}
    for group in groups:
        group_floor = max(root_floors[root] for root in group)
        earliest = max((earliest[0], True), (group_floor, False))
        infima.update(dict.fromkeys(group, earliest))
    for item in constraints["deadlines"]:
        choices = item["latest_onset_sim_s"]
        if not any(infima[root] <= (deadline, False) for root, deadline in choices.items()):
            return {
                "missed_deadline_for": item["evidence_id"],
                "conflicting_paths": [
                    {"root": root, "earliest_onset_sim_s": infima[root][0], "strictly_after": infima[root][1],
                     "onset_needed_by_sim_s": deadline}
                    for root, deadline in choices.items()
                ],
            }
    return None


def _fit_epoch(frame, model, bounds, orders_by_set):
    diagnosis = evaluate_hypotheses(frame, model=model)
    fits, histories = [], []
    for panel in diagnosis["candidates"]:
        roots = frozenset(panel["roots"])
        rejected = panel["status"] == "contradicted"
        constraints = None if rejected else _timing_constraints(frame, panel, model, bounds)
        counts = Counter()
        for groups in orders_by_set[roots]:
            conflict = None if rejected else _timing_conflict(groups, constraints)
            status = "excluded_by_dependency" if rejected else "excluded_by_timing" if conflict else panel["status"]
            entry = {"mechanism_set": panel["id"], "onset_groups": groups, "status": status}
            if conflict is not None:
                entry["timing_conflict"] = conflict
            histories.append(entry)
            counts[status] += 1
        fits.append({
            "id": panel["id"], "label": panel["label"], "roots": panel["roots"],
            "dependency_status": panel["status"], "history_counts": {name: counts[name] for name in _STATUSES},
            "dependency_evidence_support": evidence_support(panel),
            "paths": panel["dependency_paths"], "contradictions": panel["contradicting_evidence"],
            "missing_evidence": panel["missing_evidence"], "timing_constraints": constraints,
        })
    possible = [item for item in fits if item["history_counts"]["compatible"] or item["history_counts"]["unconfirmed"]]
    minimal = [item["id"] for item in possible if not any(set(other["roots"]) < set(item["roots"]) for other in possible)]
    return {
        **frame,
        "history_counts": {name: sum(item["history_counts"][name] for item in fits) for name in _STATUSES},
        "minimal_possible_mechanism_sets": minimal,
        "unique_history_within_model": (
            next(item for item in histories if item["status"] == "compatible")
            if sum(item["history_counts"]["compatible"] for item in possible) == 1
            and not any(item["history_counts"]["unconfirmed"] for item in possible) else None
        ),
        "mechanism_sets": fits, "histories": histories,
    }


def _catalogue_orders(model):
    orders_by_set = defaultdict(list, {frozenset(): [()]})
    for groups in ordered_onsets(tuple(model["roots"])):
        orders_by_set[frozenset(root for group in groups for root in group)].append(groups)
    return orders_by_set


def analyze_sequences(records, *, response_bounds=None):
    """Evaluate every onset history using public observations and optional bounds."""
    model = generated_model()
    bounds = _response_bounds(response_bounds, model)
    rows = list(records)
    first = rows[0] if rows else None
    source_schema = first.get("schema_version") if isinstance(first, dict) else None
    if source_schema == 2:
        # Historical airborne captures lack the new channels. Preserve every
        # measured value and let the existing quality checks mark them unknown.
        rows = [{**validate_airborne_observation(row), "schema_version": 3,
                 "observation_profile": PROPULSION_PROFILE_ID, "complete": False} for row in rows]
    frames = build_feature_frames(rows, generated=True, whole_epoch=True)["frames"]
    orders_by_set = _catalogue_orders(model)
    return {
        "schema_version": 1, "model_id": model["model_id"], "method": "required_paths_and_onset_constraints",
        "input_observation_schema": source_schema, "observation_count": len(rows),
        "catalogue": {"multi_fault_sets": sum(len(roots) > 1 for roots in orders_by_set),
                      "nonempty_onset_histories": sum(len(orders) for roots, orders in orders_by_set.items() if roots),
                      "reference_histories": 1},
        "response_bounds_sim_s": bounds,
        "scope": list(_SCOPE), "model_assumptions": model["assumptions"],
        "fact_labels": {name: spec["label"] for name, spec in model["facts"].items()},
        "physical_cause_identifiable": False, "probabilities_computed": False,
        "epochs": [_fit_epoch(frame, model, bounds, orders_by_set) for frame in frames],
    }


def _markdown(report):
    catalogue = report["catalogue"]
    lines = [
        "# AeroTrace onset history replay", "",
        f"Evaluated {catalogue['nonempty_onset_histories']:,} nonempty histories across "
        f"{catalogue['multi_fault_sets']} multi-fault sets and five isolated mechanisms, "
        "plus the reference history, in each clock epoch.", "",
    ]
    for epoch in report["epochs"]:
        lines.extend([f"## Epoch {epoch['epoch']}", "",
                      f"Public samples {epoch['first_sample_index']} to {epoch['last_sample_index']}.", ""])
        observed = [(name, fact["onset_interval"]) for name, fact in epoch["facts"].items() if fact["state"] == "observed"]
        if observed:
            lines.extend(["| Observed effect | Last usable nominal time (simulator seconds) | First qualifying anomaly (simulator seconds) |",
                          "| --- | ---: | ---: |"])
            for name, onset in observed:
                lower = onset["lower_sim_time_s"]
                covered = f"{lower:.2f}" if lower is not None and onset["covered_through_confirmation"] else "Unresolved"
                lines.append(f"| {report['fact_labels'][name]} | {covered} | {onset['upper_sim_time_s']:.2f} |")
            lines.append("")
        lines.extend(["| Mechanism set still possible | Compatible orders | Unconfirmed orders | Dependency checks supported |",
                      "| --- | ---: | ---: | ---: |"])
        possible = [item for item in epoch["mechanism_sets"]
                    if item["history_counts"]["compatible"] or item["history_counts"]["unconfirmed"]]
        for item in possible:
            counts = item["history_counts"]
            support = item["dependency_evidence_support"]
            score = f"{support['percent']}% ({support['supported_checks']}/{support['total_checks']})"
            lines.append(f"| {item['label']} | {counts['compatible']} | {counts['unconfirmed']} | {score} |")
        if not possible:
            lines.append("| No possible mechanism sets under this model | 0 | 0 | |")
        counts = epoch["history_counts"]
        lines.extend(["", f"{counts['excluded_by_dependency']:,} excluded by dependency checks. "
                      f"{counts['excluded_by_timing']:,} excluded by timing or a local-source witness.", ""])
        labels = {item["roots"][0]: item["label"] for item in epoch["mechanism_sets"] if len(item["roots"]) == 1}
        examples = [item for item in epoch["histories"] if item["status"] in ("compatible", "unconfirmed")
                    and item["mechanism_set"] in epoch["minimal_possible_mechanism_sets"]]
        if examples:
            lines.extend(["Smallest remaining explanations", ""])
            for item in examples[:10]:
                order = " → ".join(" + ".join(labels[root] for root in group) for group in item["onset_groups"])
                lines.append(f"- {order or 'Selected reference'} ({item['status']})")
            if len(examples) > 10:
                lines.append(f"- {len(examples) - 10:,} further orders in the JSON report.")
            lines.append("")
    lines.extend(["## Model conditions", ""])
    lines.extend(f"- {item}" for item in report["scope"])
    lines.extend(["", "The JSON report contains the paths, observation brackets, missing evidence and rejection reasons.",
                  "Its response bounds are the assumptions used for this replay. The percentage measures dependency evidence coverage."])
    return "\n".join(lines) + "\n"


def _replay_sources():
    sources = _sources()
    for filename in ("sequence_reasoning.py", "onset_orders.py"):
        sources[f"aircraft_debugger/{filename}"] = Path(__file__).with_name(filename).read_bytes()
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path, help="Public airborne observations JSONL")
    parser.add_argument("--response-bounds", type=Path, help="Optional mechanism-to-effect delay bounds JSON")
    parser.add_argument("--output", required=True, type=Path, help="New directory for the replay report")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must name a new directory")
    try:
        original = args.observations.read_bytes()
        sources = _replay_sources()
        bounds = None
        if args.response_bounds:
            bounds = json.loads(args.response_bounds.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
            if not isinstance(bounds, dict):
                raise ValueError("The response bounds file must contain a JSON object")
        report = analyze_sequences(iter_profile_observations(args.observations), response_bounds=bounds)
        if args.observations.read_bytes() != original or _replay_sources() != sources:
            raise ValueError("Public input or replay source changed during replay")
        report["observation_file_sha256"] = hashlib.sha256(original).hexdigest()
        report["executed_source_sha256"] = {name: hashlib.sha256(body).hexdigest() for name, body in sources.items()}
        args.output.mkdir(parents=True, exist_ok=False)
        _write_json(args.output / "report.json", report)
        (args.output / "report.md").write_text(_markdown(report), encoding="utf-8", newline="\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"AeroTrace sequence replay failed: {error}\n")
    print(f"Evaluated {report['catalogue']['nonempty_onset_histories']:,} histories plus reference per epoch. {args.output.resolve()}")


if __name__ == "__main__":
    main()
