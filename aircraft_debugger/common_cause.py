"""Screen observation clusters without identifying a physical initiating event."""

from collections import defaultdict


# Screening window for first observed effect times, not a propagation-delay bound.
ONSET_SCREEN_WINDOW_SIM_S = 3.0
_SURVIVING = {"compatible", "unconfirmed"}


def _qualified_clusters(observed, continuations):
    qualified, unqualified = [], []
    for item in observed:
        onset = item["onset_interval"]
        if item["fact"] in continuations:
            continue
        if (onset and onset["covered_through_confirmation"]
                and onset["lower_sim_time_s"] is not None
                and onset["lower_sim_time_s"] < onset["upper_sim_time_s"]):
            qualified.append((onset["upper_sim_time_s"], item["fact"]))
        else:
            unqualified.append(item["fact"])
    qualified.sort()
    windows = list(dict.fromkeys(
        frozenset(fact for time, fact in qualified if start <= time <= start + ONSET_SCREEN_WINDOW_SIM_S)
        for start, _ in qualified
    ))
    clusters = [sorted(window) for window in windows
                if len(window) >= 2 and not any(window < other for other in windows)]
    return clusters, unqualified


def _downstream_continuations(epoch, viable, histories, timing_conflict):
    """An earlier observed predecessor can already explain a later conditional effect."""
    facts = epoch["facts"]
    matches = defaultdict(list)
    minimal = set(epoch["minimal_possible_mechanism_sets"])
    for candidate in viable:
        if candidate["id"] not in minimal:
            continue
        for path in candidate["paths"]:
            if path["necessity"] != "conditional":
                continue
            root, parent, effect = path["nodes"][0], path["nodes"][-2], path["fact"]
            if parent not in facts:
                continue
            prior, later = (facts[name]["onset_interval"] for name in (parent, effect))
            if (not prior or not later or not prior["covered_through_confirmation"]
                    or not later["covered_through_confirmation"] or later["lower_sim_time_s"] is None
                    or prior["upper_sim_time_s"] + ONSET_SCREEN_WINDOW_SIM_S >= later["lower_sim_time_s"]):
                continue
            if any(_fits_assigned_group(order, candidate["timing_constraints"], (parent, effect), (root,),
                                        timing_conflict) for order in histories[candidate["id"]]):
                matches[effect].append({"earlier_effect": parent, "mechanism": root, "set": candidate["id"]})
    return dict(matches)


def _fits_assigned_group(history, constraints, effects, group, timing_conflict):
    deadlines = []
    for deadline in constraints["deadlines"]:
        if deadline["evidence_id"] not in effects:
            deadlines.append(deadline)
            continue
        eligible = {root: time for root, time in deadline["latest_onset_sim_s"].items() if root in group}
        if not eligible:
            return False
        deadlines.append({**deadline, "latest_onset_sim_s": eligible})
    return timing_conflict(history, {**constraints, "deadlines": deadlines}) is None


def _cluster_paths(effects, viable, histories, timing_conflict):
    single, joint = defaultdict(list), []
    for candidate in viable:
        constraints = candidate["timing_constraints"]
        sources = [set(item["latest_onset_sim_s"]) for item in constraints["deadlines"]
                   if item["evidence_id"] in effects]
        if len(sources) != len(effects):
            continue
        orders = histories[candidate["id"]]
        for root in sorted(set.intersection(*sources)):
            if any(_fits_assigned_group(order, constraints, effects, (root,), timing_conflict) for order in orders):
                single[root].append(candidate["id"])
        if any(_fits_assigned_group(order, constraints, effects, group, timing_conflict)
               for order in orders for group in order if len(group) > 1):
            joint.append(candidate["id"])
    return dict(single), joint


def _mismatch(epoch, viable, timing_failures):
    if viable:
        return {"status": "joint_fit_retained", "unexplained_observations": [], "nearest_fits": []}
    # A local mismatch in a nearest set is not a uniquely unexplained effect.
    residuals = []
    for candidate in epoch["mechanism_sets"]:
        contradictions = candidate["contradictions"]
        examples = list(timing_failures.get(candidate["id"], {}).values())
        if contradictions:
            residuals.append((len(contradictions), {
                "id": candidate["id"], "contradictions": contradictions, "timing_conflict_examples": [],
            }))
        elif examples:
            # Each example identifies a sufficient reason to exclude one order.
            residuals.append((1, {
                "id": candidate["id"], "contradictions": [], "timing_conflict_examples": examples,
            }))
    fewest = min((count for count, _ in residuals), default=0)
    nearest = [item for count, item in residuals if count == fewest]
    observed = {name for name, fact in epoch["facts"].items() if fact["state"] == "observed"}
    unexplained = []
    for name in sorted(observed):
        affected = [item["id"] for item in nearest if
                    any(clash.get("fact") == name for clash in item["contradictions"])
                    or any(example["conflict"].get("missed_deadline_for") == name
                           for example in item["timing_conflict_examples"])]
        if affected:
            unexplained.append({"fact": name, "rejected_in_nearest_sets": affected})
    return {
        "status": "no_joint_model_fit", "unexplained_observations": unexplained, "nearest_fits": nearest,
        "limitation": ("A coverage, measurement or model conflict can prevent a joint fit. "
                       "Residuals are examples of failed predictions, with no attribution to a physical cause."),
    }


def investigate_common_cause(epoch, viable, observed, timing_conflict, timing_failures):
    mismatch = _mismatch(epoch, viable, timing_failures)
    histories = defaultdict(list)
    for item in epoch["histories"]:
        if item["status"] in _SURVIVING:
            histories[item["mechanism_set"]].append(item["onset_groups"])
    continuations = _downstream_continuations(epoch, viable, histories, timing_conflict)
    windows, unqualified = _qualified_clusters(observed, continuations)
    clusters = []
    for effects in windows:
        single, joint = _cluster_paths(effects, viable, histories, timing_conflict)
        declared = [candidate["roots"][0] for candidate in epoch["mechanism_sets"]
                    if len(candidate["roots"]) == 1 and set(effects) <= {path["fact"] for path in candidate["paths"]}]
        if single:
            status = "known_shared_path_fits"
            reason = "An existing mechanism can account for the clustered effects in at least one surviving history."
        elif joint:
            status = "shared_origin_unresolved"
            reason = ("The cluster spans paths requiring multiple modelled mechanisms. A hidden common disturbance "
                      "and close independent failures have no distinct physical signature in the selected observations.")
        elif viable:
            status = "distinct_mechanism_onsets_required"
            reason = ("Surviving histories need separate mechanism onsets to account for this cluster. The model "
                      "cannot assess whether an unobserved disturbance reached the paths at different times.")
        else:
            status = "cluster_in_model_mismatch"
            reason = "There is no joint catalogue fit for the incident. Timing does not link the cluster to a single disturbance."
        clusters.append({
            "effects": effects, "status": status, "reason": reason,
            "declared_single_path_roots": declared, "known_shared_paths": single,
            "surviving_sets_with_common_mechanism_onset": joint,
            "surviving_sets_retained": [candidate["id"] for candidate in viable],
            "unmodelled_common_cause_possible": status == "shared_origin_unresolved",
            "physical_initiator": "unknown",
            "distinctive_shared_evidence": [],
        })
    return {
        "clusters": clusters, "unqualified_onsets": unqualified, "possible_downstream_continuations": continuations,
        "screen_window_sim_s": ONSET_SCREEN_WINDOW_SIM_S,
        "model_mismatch": mismatch,
        "exposure_model_available": False,
        "distinguishing_evidence_needed": (
            "An independently observed shared upstream disturbance, a verified shared supply or exposure with the "
            "right chronology, or component-local evidence distinguishing separate failures. These tests are outside "
            "the current shared-exposure model."
        ),
        "limitation": (
            "Grouping uses first observed effects within a fixed screening window. Effects already explainable "
            "as continuations of earlier paths are omitted from this screen only. A common mechanism-onset history "
            "can also represent coincident independent failures. Qualified effect brackets do not determine physical "
            "onsets or exclude a disturbance with delayed responses. The graph covers selected dependencies only."
        ),
    }
