"""Passive discrimination and counterfactual queries over fitted explanations."""

from collections import defaultdict

from .common_cause import investigate_common_cause
from .hypotheses import _predictions
from .propulsion_features import SUPPLY_CHANNELS, _backup_condition


_RESULTS = ("observed", "not_observed")
_MASKED = ("potentially_masked", "possible_with_missing_evidence")


def _fit_status(candidate):
    counts = candidate["history_counts"]
    if counts["compatible"]:
        return "compatible"
    if counts["unconfirmed"]:
        return "unconfirmed"
    return "excluded"


def _viable_candidates(epoch):
    return [item for item in epoch["mechanism_sets"] if _fit_status(item) != "excluded"]


def _roots(values, model):
    if not isinstance(values, (tuple, list, set, frozenset)):
        raise ValueError("Mechanism restrictions must be collections of root IDs")
    if any(not isinstance(root, str) or root not in model["roots"] for root in values):
        raise ValueError("Counterfactual names a mechanism outside the selected model")
    return frozenset(values)


def _timing_failure_index(epoch):
    timing_failures = defaultdict(dict)
    for history in epoch["histories"]:
        if history["status"] == "excluded_by_timing":
            conflict = history["timing_conflict"]
            key = conflict.get("missed_deadline_for") or tuple(conflict["missing_witness_paths"])
            timing_failures[history["mechanism_set"]].setdefault(key, {
                "example_onset_groups": history["onset_groups"], "conflict": conflict,
            })
    return timing_failures


def evaluate_counterfactual(epoch, model, *, require=(), exclude=(), only=None, _timing_failures=None):
    """Constrain the actual fitted catalogue. This query makes no simulator changes."""
    required = _roots(require, model)
    excluded = _roots(exclude, model)
    exact = None if only is None else _roots(only, model)
    if required & excluded or (exact is not None and (not required <= exact or exact & excluded)):
        raise ValueError("Counterfactual mechanism restrictions conflict")
    matched, rejected = [], []
    timing_failures = _timing_failure_index(epoch) if _timing_failures is None else _timing_failures
    for candidate in epoch["mechanism_sets"]:
        roots = set(candidate["roots"])
        if not required <= roots or excluded & roots or (exact is not None and roots != exact):
            continue
        status = _fit_status(candidate)
        item = {"id": candidate["id"], "roots": candidate["roots"], "status": status,
                "history_counts": candidate["history_counts"]}
        if status == "excluded":
            item.update(contradictions=candidate["contradictions"],
                        timing_conflict_examples=list(timing_failures[item["id"]].values()))
            rejected.append(item)
        else:
            matched.append(item)
    status = "no_modelled_candidate"
    if matched:
        status = "compatible" if any(item["status"] == "compatible" for item in matched) else "unconfirmed"
    elif rejected:
        status = "excluded"
    return {"require": sorted(required), "exclude": sorted(excluded),
            "only": None if exact is None else sorted(exact), "status": status,
            "surviving_explanations": matched, "rejected_explanations": rejected}


def _equivalent_groups(candidates, predictions, facts):
    groups = defaultdict(list)
    for candidate in candidates:
        signature = tuple(predictions[candidate][name]["expected"] for name in facts)
        groups[signature].append(candidate)
    return [group for group in groups.values() if len(group) > 1]


def select_evidence(epoch, model, viable=None):
    """Partition fits under each conclusive value of an unresolved observation."""
    viable = _viable_candidates(epoch) if viable is None else viable
    candidates = [item["id"] for item in viable]
    available = set(epoch.get("investigation_context", {}).get("usable_channels", ()))
    unknown = [name for name, fact in epoch["facts"].items() if fact["state"] == "unknown"]
    predictions = {item["id"]: _predictions(item["roots"], model)[0] for item in viable}
    tests = []
    for name in unknown:
        partitions = {outcome: [candidate for candidate in candidates
                                if predictions[candidate][name]["expected"] in (outcome, "allowed")]
                      for outcome in _RESULTS}
        if not all(partitions.values()) or partitions["observed"] == partitions["not_observed"]:
            continue
        fact = epoch["facts"][name]
        channels = model["facts"][name]["channels"]
        coverage = fact.get("coverage", {})
        if not set(channels) <= available:
            availability = "unavailable_or_unusable"
        elif coverage.get("unavailable_sample_indices") or coverage.get("timestamp_gaps"):
            availability = "needs_incident_history"
        else:
            availability = "available"
        counts = [len(partition) for partition in partitions.values()]
        require_effect = len(candidates) - len(partitions["not_observed"])
        require_absence = len(candidates) - len(partitions["observed"])
        conditional = len(candidates) - require_effect - require_absence
        partitions["unknown"] = list(candidates)
        tests.append({
            "fact": name, "label": model["facts"][name]["label"], "channels": channels,
            "availability": availability, "passive": True,
            "predicted_partitions": partitions,
            "worst_case_remaining": max(counts), "best_case_remaining": min(counts),
            "minimum_eliminated_if_conclusive": len(candidates) - max(counts),
            "why": (f"{require_effect} sets require this effect, {require_absence} predict its absence, "
                    f"and {conditional} allow either conclusive result."),
        })
    tests.sort(key=lambda item: (item["worst_case_remaining"], item["best_case_remaining"], item["fact"]))
    ready = [item for item in tests if item["availability"] == "available"]
    held = [item for item in tests if item["availability"] != "available"]
    if not candidates:
        status = "no_surviving_root_sets"
    elif len(candidates) == 1:
        status = "no_competing_root_sets"
    elif ready:
        status = "passive_discriminator_available"
    elif held:
        status = "no_actionable_discriminator"
    else:
        status = "no_modelled_passive_discriminator"
    return {
        "status": status, "candidate_count": len(candidates),
        "recommended_measurements": ready, "unavailable_discriminators": held,
        "equivalent_prediction_groups": _equivalent_groups(candidates, predictions, unknown),
        "currently_indistinguishable_groups": _equivalent_groups(
            candidates, predictions, [item["fact"] for item in ready]),
        "ranking": "Fewest remaining root sets in the worst conclusive outcome, then the best outcome, then fact ID.",
        "scope": ("Hypothetical usable evidence for the same incident window. A fresh later reading cannot fill a historical gap. "
                  "Predictions concern the presence of an effect, without a new timestamp. An unknown result eliminates nothing."),
    }


def _yellow_backup_witness(epoch):
    relation = epoch["temporal_relations"].get("yellow_pressure_follows_measured_supply", {})
    if relation.get("status") != "consistent":
        return None
    samples = defaultdict(dict)
    for point in relation["evidence"]:
        samples[point["sample_index"]][point["channel"]] = point
    for points in samples.values():
        if _backup_condition(points) == "supported by alternate supply":
            return [points[channel] for channel in SUPPLY_CHANNELS]
    return None


def _candidate_observability(candidate, smaller, facts):
    paths = candidate["paths"]
    required = {path["fact"] for path in paths if path["necessity"] == "required"}
    constraints = candidate["timing_constraints"]
    mechanisms = []
    for root in candidate["roots"]:
        local = [path for path in paths if path["nodes"][0] == root]
        shared = [path["fact"] for path in local if facts[path["fact"]]["state"] == "observed"]
        exclusive = [item["evidence_id"] for item in constraints["deadlines"]
                     if set(item["latest_onset_sim_s"]) == {root}]
        missing = [path["fact"] for path in local
                   if path["necessity"] == "required" and facts[path["fact"]]["state"] == "unknown"]
        omitting = [item["id"] for item in smaller if root not in item["roots"]]
        if exclusive:
            role = "supported_within_candidate"
        elif omitting:
            role = "possible_with_missing_evidence" if missing else "potentially_masked"
        else:
            role = "needed_for_fit_within_candidate"
        mechanisms.append({
            "mechanism": root, "status": role, "exclusive_witness_ids": exclusive,
            "observed_effects_on_path": list(dict.fromkeys(shared)),
            "unknown_required_effects": list(dict.fromkeys(missing)),
            "smaller_fits_without_mechanism": omitting,
        })
    return {
        "id": candidate["id"], "label": candidate["label"], "roots": candidate["roots"],
        "status": _fit_status(candidate), "history_counts": candidate["history_counts"],
        "required_observed_effects": [name for name, fact in facts.items()
                                      if name in required and fact["state"] == "observed"],
        "required_unknown_effects": [name for name, fact in facts.items()
                                     if name in required and fact["state"] == "unknown"],
        "mechanisms": mechanisms,
    }


def _conditional_downstream(epoch, viable):
    """Find absent/unmeasured consequences of observed upstream effects."""
    facts = epoch["facts"]
    backup = _yellow_backup_witness(epoch)
    results = {}
    for candidate in viable:
        for path in candidate["paths"]:
            upstream = path["nodes"][-2]
            name = path["fact"]
            if (path["necessity"] != "conditional" or upstream not in facts
                    or facts[upstream]["state"] != "observed"):
                continue
            state = facts[name]["state"]
            witness = backup if name == "yellow_line_pressure_loss" else None
            if state == "observed" and witness is None:
                continue
            key = (upstream, name)
            item = results.setdefault(key, {
                "upstream_observed_effect": upstream, "downstream_effect": name,
                "downstream_observation": state, "compatible_sets": [],
                "alternate_supply_witness": witness,
                "status": ("measured_retention_with_backup" if witness else
                           "downstream_unobservable" if state == "unknown" else "conditional_effect_not_observed"),
                "model_reason": path["reason"],
            })
            if candidate["id"] not in item["compatible_sets"]:
                item["compatible_sets"].append(candidate["id"])
    return list(results.values())


def investigate_masking(epoch, viable):
    facts = epoch["facts"]
    root_sets = {item["id"]: set(item["roots"]) for item in viable}
    compatible = [item for item in viable if _fit_status(item) == "compatible"]
    minimal_compatible = [item["id"] for item in compatible
                          if not any(root_sets[other["id"]] < root_sets[item["id"]] for other in compatible)]
    minimal_possible = set(epoch["minimal_possible_mechanism_sets"])
    candidates, hidden = [], {}
    for item in viable:
        smaller = [other for other in viable if root_sets[other["id"]] < root_sets[item["id"]]]
        assessment = _candidate_observability(item, smaller, facts)
        candidates.append(assessment)
        for mechanism in assessment["mechanisms"]:
            status = mechanism["status"]
            if status in _MASKED:
                record = hidden.setdefault(mechanism["mechanism"], {
                    "mechanism": mechanism["mechanism"], "candidate_sets": [],
                    "status": "compatible_but_unconfirmed",
                    "limitation": "A smaller surviving set explains the observed effects without this mechanism.",
                })
                record["candidate_sets"].append({
                    "id": item["id"], "status": status,
                    "smaller_fits_without_mechanism": mechanism["smaller_fits_without_mechanism"],
                })
    blue = None
    if facts["blue_pressure_loss"]["state"] == facts["blue_inventory_loss"]["state"] == "observed":
        relation = epoch["temporal_relations"]["inventory_before_pressure"]
        blue = {
            "inventory_pressure_relation": relation,
            "quantity_at_first_observed_pressure_loss": epoch.get("investigation_context", {}).get(
                "blue_quantity_at_pressure_loss"),
            "limitation": ("The selected model has no depletion threshold linking indicated quantity to pressure. "
                           "The same-poll indication alone cannot separate depletion from a concurrent supply loss."),
        }
    return {
        "minimal_compatible_explanations": minimal_compatible,
        "minimal_possible_explanations": epoch["minimal_possible_mechanism_sets"],
        "additional_compatible_fault_sets": [item["id"] for item in compatible if item["id"] not in minimal_compatible],
        "additional_possible_fault_sets": [item["id"] for item in viable if item["id"] not in minimal_possible],
        "potentially_masked_mechanisms": list(hidden.values()),
        "candidate_observability": candidates,
        "conditional_downstream_effects": _conditional_downstream(epoch, viable),
        "blue_supply_discrimination": blue,
    }


def investigate_epoch(epoch, model, timing_conflict, *, query=None):
    """Attach an investigation to an epoch without changing its fit."""
    viable = _viable_candidates(epoch)
    timing_failures = _timing_failure_index(epoch)
    observed = [{"fact": name, "label": model["facts"][name]["label"],
                 "onset_interval": fact["onset_interval"], "evidence": fact["evidence"]}
                for name, fact in epoch["facts"].items() if fact["state"] == "observed"]
    queries = [{"exclude": [root]} for root in model["roots"]
               if any(root in item["roots"] for item in viable)]
    return {
        "schema_version": 1,
        "observed_abnormalities": observed,
        "masking": investigate_masking(epoch, viable),
        "evidence_selection": select_evidence(epoch, model, viable),
        "common_cause": investigate_common_cause(epoch, viable, observed, timing_conflict, timing_failures),
        "counterfactuals": [evaluate_counterfactual(epoch, model, _timing_failures=timing_failures, **restriction)
                            for restriction in queries + ([query] if query is not None else [])],
    }
