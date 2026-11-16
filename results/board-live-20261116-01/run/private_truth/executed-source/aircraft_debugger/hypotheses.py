"""Small executable, observation-only hypothesis model for AeroTrace.

This is a finite engineering compatibility model, not calibrated probability or
an independently validated aircraft solver. Predictions are reached through the
declared dependency graph. The public feature builder owns evidence quality,
clock epochs and incident boundaries; this evaluator never opens a file or joins
incidents. Retained bus supply and retained early pressure are allowed outcomes.
"""

from __future__ import annotations

import copy
from itertools import combinations

from .propulsion_features import PROPULSION_FACTS


_GEN_ROOT = "generator_2_source_path_fault"
_BLUE_ROOT = "blue_fluid_loss_mechanism"
_FACTS = (
    "generator_source_anomaly", "blue_inventory_loss",
    "bus_supply_loss", "blue_pressure_loss",
)


def default_model() -> dict:
    """Return a fresh inspectable model; no native rate/delay is copied into it."""
    return {
        "schema_version": 1,
        "model_id": "aerotrace-two-mechanism-compatibility-v1",
        "method": "dependency_predictions_and_optional_temporal_consistency",
        "provenance": {
            "implementation": "aircraft_debugger/hypotheses.py",
            "mechanism_mapping": "docs/ENGINEERING-REPORT.md",
            "observability": "docs/ARCHITECTURE.md",
            "classification": "Project-authored finite compatibility model; no external physical validation or probability calibration",
        },
        "roots": [_GEN_ROOT, _BLUE_ROOT],
        "facts": {
            "generator_source_anomaly": {
                "label": "Generator 2 source-output anomaly",
                "channels": ["generator_2_voltage"],
            },
            "blue_inventory_loss": {
                "label": "Reported Blue reservoir quantity decline",
                "channels": ["blue_quantity"],
            },
            "bus_supply_loss": {
                "label": "Monitored bus-2 supply loss/degradation",
                "channels": ["ac_bus_2"],
            },
            "blue_pressure_loss": {
                "label": "Blue pressure below the selected retained range",
                "channels": ["blue_pressure"],
            },
        },
        "nodes": [
            {"id": _GEN_ROOT, "kind": "hypothesized_mechanism"},
            {"id": _BLUE_ROOT, "kind": "hypothesized_mechanism"},
            *[{"id": fact, "kind": "observable_effect"} for fact in _FACTS],
        ],
        "edges": [
            {
                "from": _GEN_ROOT, "to": "generator_source_anomaly", "necessity": "required",
                "reason": "The selected source-path mechanism predicts abnormal generator-2 output.",
            },
            {
                "from": "generator_source_anomaly", "to": "bus_supply_loss", "necessity": "conditional",
                "reason": "Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.",
            },
            {
                "from": _BLUE_ROOT, "to": "blue_inventory_loss", "necessity": "required",
                "reason": "The selected fluid-loss analogue predicts inventory decline from an observed reference.",
            },
            {
                "from": "blue_inventory_loss", "to": "blue_pressure_loss", "necessity": "conditional",
                "reason": "Pressure can degrade as inventory/supply becomes insufficient; early retained pressure and subsequent restoration lag are allowed. No exact delay is assumed.",
            },
        ],
        "candidates": [
            {
                "id": "selected_reference", "label": "No selected mechanism currently required",
                "roots": [], "kind": "reference",
                "scope_note": "Selected-observation reference, not whole-aircraft health.",
            },
            {
                "id": "generator_2_source_path_fault", "label": "Generator 2 source-path fault",
                "roots": [_GEN_ROOT], "kind": "single_mechanism",
                "scope_note": "One compatible source-path mechanism does not identify a generator component, engine/drive fault, switching state or repair.",
            },
            {
                "id": "blue_inventory_loss", "label": "Blue fluid-inventory-loss analogue",
                "roots": [_BLUE_ROOT], "kind": "single_mechanism",
                "scope_note": "A supported fluid-loss analogue, not unique identification of an external leak or validated lost volume.",
            },
            {
                "id": "independent_pair", "label": "Independent source-path and blue inventory-loss mechanisms",
                "roots": [_GEN_ROOT, _BLUE_ROOT], "kind": "multiple_initiators",
                "scope_note": "Independent initiating mechanisms are a candidate history; component-command recipes do not establish statistical independence.",
            },
            {
                "id": "grouped_joint_event", "label": "One grouped event affecting both selected mechanisms",
                "roots": [_GEN_ROOT, _BLUE_ROOT], "kind": "conditional_shared_initiator",
                "scope_note": "Conditional co-exposure hypothesis only. Native damage geometry, debris and common physical origin are unverified.",
            },
        ],
        "temporal_constraints": [
            {
                "id": "inventory_before_pressure", "root": _BLUE_ROOT,
                "reason": "For this selected depletion mechanism, observed inventory loss should not be definitely later than related pressure degradation. Overlapping/unknown onset intervals remain unresolved.",
            },
        ],
        "assumptions": [
            "Predictions apply to the supplied selected incident/epoch, not all aircraft systems or unobserved prehistory.",
            "Within this finite catalogue, an effect unreachable from a candidate's roots is not explained by that candidate; a usable contrary observation rejects it.",
            "Required effect absence is evaluated as observed absence in the current feature scope; candidates are reevaluated as evidence evolves, not permanently eliminated.",
            "Conditional edges allow both retained and degraded downstream output; missing measurements never count as contradiction.",
            "The independent and grouped candidates have identical observable signatures and temporal rules. No prior, complexity preference or initiating-event count breaks their tie.",
            "Detector thresholds belong to the reused evidence layer, not this hypothesis model; no native depletion rates or fixed delays are fitted here.",
        ],
    }


_PRESSURE_ROOT = "blue_pressure_supply_loss"
V2_MODEL_ID = "aerotrace-three-mechanism-compatibility-v2"
V3_MODEL_ID = "aerotrace-engine-drive-compatibility-v3"
V4_MODEL_ID = "aerotrace-generated-mechanism-sets-v4"
MODEL_VERSIONS = ("v1", "v2", "v3", "v4")
_ENGINE_ROOT = "engine_2_power_loss"
_EDP_ROOT = "yellow_engine_driven_pump_supply_loss"
_PROPULSION_CANDIDATES = {
    _ENGINE_ROOT: ("Engine 2 power loss", [_ENGINE_ROOT], "single_mechanism",
                   "Low fuel flow and low core speed support the represented functional loss. Initiating damage, fuel starvation and commanded shutdown remain distinct possibilities."),
    _EDP_ROOT: ("Local Yellow engine-driven pump supply loss", [_EDP_ROOT], "single_mechanism",
                "Reduced pump output with engine drive retained leaves the local component or switch state unresolved."),
    "independent_generator_yellow_pump_loss": ("Separate generator 2 and Yellow pump supply losses",
        [_GEN_ROOT, _EDP_ROOT], "multiple_initiators",
        "Both source outputs fall while the observed engine drive is retained. The observations do not establish statistical independence or exclude every shared cause."),
    "independent_engine_blue_pressure_loss": ("Engine 2 power loss and separate Blue pressure-supply loss",
        [_ENGINE_ROOT, _PRESSURE_ROOT], "multiple_initiators",
        "The engine-drive path accounts for generator and Yellow pump loss. The extra Blue pressure loss requires another path in the selected model."),
    "grouped_engine_blue_pressure_loss": ("One event affecting engine drive and Blue pressure supply",
        [_ENGINE_ROOT, _PRESSURE_ROOT], "conditional_shared_initiator",
        "A shared physical event is a candidate history. These observations also fit separate initiators and leave damage geometry unresolved."),
}


def pressure_supply_model() -> dict:
    """Opt-in pressure-supply extension; existing four observed facts are reused.

    A net pressure-supply-path loss can coexist with retained inventory. This
    does not uniquely diagnose an electric pump, switch, power or sensor fault.
    Native confirmation and operating-condition limits live in the mechanism doc.
    """
    model = default_model()
    model["model_id"] = V2_MODEL_ID
    model["provenance"]["mechanism_mapping"] = "docs/ENGINEERING-REPORT.md"
    model["roots"].append(_PRESSURE_ROOT)
    model["nodes"].insert(2, {"id": _PRESSURE_ROOT, "kind": "hypothesized_mechanism"})
    model["edges"].append({"from": _PRESSURE_ROOT, "to": "blue_pressure_loss", "necessity": "required",
        "reason": "The represented net blue pressure-supply-path loss predicts degraded pressure without requiring inventory loss; alternate supply and component identity are not observed."})
    for name,label,roots,kind in [
        (_PRESSURE_ROOT,"Blue pressure-supply-path loss",[_PRESSURE_ROOT],"single_mechanism"),
        ("independent_pressure_pair","Independent source-path and blue pressure-supply losses",[_GEN_ROOT,_PRESSURE_ROOT],"multiple_initiators"),
        ("grouped_pressure_joint_event","One grouped event affecting source and blue pressure supply",[_GEN_ROOT,_PRESSURE_ROOT],"conditional_shared_initiator"),
    ]:
        model["candidates"].append({"id":name,"label":label,"roots":roots,"kind":kind,
            "scope_note":"Bounded pressure-supply configuration, not unique identification of an electric pump, switching state, sensor or physical common origin. Inventory-loss alternatives remain separate."})
    model["assumptions"].append("The pressure extension covers a pressure-supply-only configuration and its source-path pair. Inventory-plus-supply and triple-root histories are not represented; this is not an exhaustive fault catalogue.")
    return model


def propulsion_model() -> dict:
    """Opt-in version 3 catalogue with measured Engine 2 and Yellow supply paths."""
    model = pressure_supply_model()
    model["model_id"] = V3_MODEL_ID
    model["provenance"]["mechanism_mapping"] = "docs/ENGINE-DRIVE-STUDY.md"
    model["roots"].extend((_ENGINE_ROOT, _EDP_ROOT))
    model["nodes"].extend({"id": root, "kind": "hypothesized_mechanism"} for root in (_ENGINE_ROOT, _EDP_ROOT))
    for name, (channel, label) in PROPULSION_FACTS.items():
        model["facts"][name] = {"label": label, "channels": [channel]}
        model["nodes"].append({"id": name, "kind": "observable_effect"})
    for source, target, necessity, reason in (
        (_ENGINE_ROOT, "engine_2_fuel_flow_loss", "required", "The represented power-loss pattern predicts low fuel flow."),
        (_ENGINE_ROOT, "engine_2_core_speed_loss", "required", "Loss of combustion drive predicts a decrease in the measured core speed."),
        ("engine_2_core_speed_loss", "generator_source_anomaly", "required", "Insufficient core drive removes generator 2 output in this tested condition."),
        ("engine_2_core_speed_loss", "yellow_edp_output_loss", "required", "The engine-driven Yellow pump needs core rotation. The represented cutoff episode progresses through pump output loss."),
        (_EDP_ROOT, "yellow_edp_output_loss", "required", "A local Yellow pump supply loss predicts reduced engine-driven output with core drive retained."),
        ("yellow_edp_output_loss", "yellow_line_pressure_loss", "conditional", "Measured alternate supply can maintain Yellow line pressure. A settled-window check uses pump, transfer, quantity and line observations."),
    ):
        model["edges"].append({"from": source, "to": target, "necessity": necessity, "reason": reason})
    for root in (_ENGINE_ROOT, _EDP_ROOT):
        model["temporal_constraints"].append({
            "id": "yellow_pressure_follows_measured_supply", "root": root,
            "reason": "Given observed low primary output, adequate inventory and settled backup state, Yellow line pressure should track whether alternate pressure is available.",
        })
    for name, (label, roots, kind, note) in _PROPULSION_CANDIDATES.items():
        model["candidates"].append({"id": name, "label": label, "roots": list(roots), "kind": kind, "scope_note": note})
    model["assumptions"].append(
        "Propulsion predictions cover a sustained Engine 2 cutoff-like response in the pinned FlightGear study. "
        "Windmilling, partial thrust loss and additional Yellow supply mechanisms may yield other effects."
    )
    return model


def model_for_version(version: str) -> dict:
    return {"v1": default_model, "v2": pressure_supply_model,
            "v3": propulsion_model, "v4": generated_model}[version]()


def uses_propulsion_profile(model: dict) -> bool:
    return model["model_id"] in (V3_MODEL_ID, V4_MODEL_ID)


def _generated_candidates(roots):
    labels = {
        _GEN_ROOT: "Generator 2 source-path loss", _BLUE_ROOT: "Blue inventory loss",
        _PRESSURE_ROOT: "Blue pressure-supply loss", _ENGINE_ROOT: "Engine 2 power loss",
        _EDP_ROOT: "Local Yellow engine-driven pump loss",
    }
    for count in range(len(roots) + 1):
        for members in combinations(roots, count):
            yield {
                "id": "+".join(members) or "selected_reference",
                "label": " + ".join(labels[root] for root in members) or "No selected mechanism currently required",
                "roots": list(members), "kind": "generated_root_set",
                "scope_note": "The selected mechanism set is evaluated against observable effects. Initiating history can remain ambiguous.",
            }


def generated_model() -> dict:
    """Generate every subset of the five mechanism roots for observation-only replay."""
    model = propulsion_model()
    model["model_id"] = V4_MODEL_ID
    model["provenance"]["mechanism_mapping"] = "docs/FAULT-SEQUENCE-STUDY.md"
    model["candidates"] = list(_generated_candidates(model["roots"]))
    model["temporal_constraints"][0]["unless_root"] = _PRESSURE_ROOT
    model["temporal_constraints"].extend([
        {"id": "generator_loss_with_drive_retained", "root": _ENGINE_ROOT, "unless_root": _GEN_ROOT,
         "reason": "The cutoff-like engine drive loss cannot account for generator loss while measured drive is retained."},
        {"id": "yellow_pump_loss_with_drive_retained", "root": _ENGINE_ROOT, "unless_root": _EDP_ROOT,
         "reason": "The cutoff-like engine drive loss cannot account for Yellow pump loss while measured drive is retained."},
    ])
    # The generated catalogue replaces the older, explicitly authored candidate groups.
    model["assumptions"] = [note for note in model["assumptions"] if not note.startswith(
        ("The independent and grouped candidates", "The pressure extension covers"))]
    model["assumptions"].extend([
        "All subsets of the five selected mechanism classes are considered. Minimal compatible sets explain the observed facts without an extra root. Additional compatible roots may be masked.",
        "A root set can fit more than one initiating history. Observation timing can constrain separate paths without identifying every command order or physical shared cause.",
    ])
    return model


def _validate_model(model: dict) -> None:
    if not isinstance(model, dict) or model.get("schema_version") != 1:
        raise ValueError("Expected a version-1 hypothesis model")
    if not isinstance(model.get("model_id"), str) or not model["model_id"]:
        raise ValueError("Hypothesis model needs an identity")
    generated = model["model_id"] == V4_MODEL_ID
    propulsion = uses_propulsion_profile(model)
    extended = propulsion or model["model_id"] == V2_MODEL_ID
    supported_roots = {_GEN_ROOT, _BLUE_ROOT} | ({_PRESSURE_ROOT} if extended else set())
    if propulsion:
        supported_roots.update((_ENGINE_ROOT, _EDP_ROOT))
    facts = set(_FACTS) | (set(PROPULSION_FACTS) if propulsion else set())
    roots = model.get("roots", [])
    if len(roots) != len(supported_roots) or set(roots) != supported_roots:
        raise ValueError("Model roots differ from the selected bounded catalogue")
    if not isinstance(model.get("facts"), dict) or set(model["facts"]) != facts:
        raise ValueError("Hypothesis model facts must match the selected catalogue")
    nodes = model.get("nodes")
    if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
        raise ValueError("Hypothesis model needs typed nodes")
    ids = [node.get("id") for node in nodes]
    if len(set(ids)) != len(ids) or set(ids) != facts | supported_roots:
        raise ValueError("Hypothesis nodes must match the supported roots and effects")
    edges = model.get("edges")
    if not isinstance(edges, list):
        raise ValueError("Hypothesis model edges must be a list")
    adjacency = {node: [] for node in ids}
    seen = set()
    for edge in edges:
        if (not isinstance(edge, dict) or edge.get("from") not in adjacency
                or edge.get("to") not in adjacency or edge.get("necessity") not in {"required", "conditional"}
                or not isinstance(edge.get("reason"), str)):
            raise ValueError("Invalid executable dependency edge")
        pair = edge["from"], edge["to"]
        if pair in seen:
            raise ValueError("Duplicate executable dependency edge")
        seen.add(pair)
        adjacency[pair[0]].append(pair[1])
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise ValueError("Executable prediction graph must be acyclic")
        if node in visited:
            return
        visiting.add(node)
        for target in adjacency[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in ids:
        visit(node)
    expected_roots = {
        "selected_reference": set(), "generator_2_source_path_fault": {_GEN_ROOT},
        "blue_inventory_loss": {_BLUE_ROOT}, "independent_pair": {_GEN_ROOT, _BLUE_ROOT},
        "grouped_joint_event": {_GEN_ROOT, _BLUE_ROOT},
    }
    if extended:
        expected_roots.update({_PRESSURE_ROOT: {_PRESSURE_ROOT},
            "independent_pressure_pair": {_GEN_ROOT, _PRESSURE_ROOT},
            "grouped_pressure_joint_event": {_GEN_ROOT, _PRESSURE_ROOT}})
    if propulsion:
        expected_roots.update({name: set(definition[1]) for name, definition in _PROPULSION_CANDIDATES.items()})
    if generated:
        expected_roots = {item["id"]: set(item["roots"]) for item in _generated_candidates(roots)}
    candidates = model.get("candidates")
    if (not isinstance(candidates, list) or len(candidates) != len(expected_roots)
            or {candidate.get("id") for candidate in candidates if isinstance(candidate, dict)} != set(expected_roots)):
        raise ValueError("Expected the selected bounded candidate definitions")
    by_id = {candidate["id"]: candidate for candidate in candidates}
    for name, candidate in by_id.items():
        roots = candidate.get("roots")
        if (not isinstance(roots, list) or len(roots) != len(set(roots))
                or set(roots) != expected_roots[name] or not isinstance(candidate.get("label"), str)):
            raise ValueError("Invalid bounded candidate root definition")
    constraints = model.get("temporal_constraints")
    permitted_constraints = {("inventory_before_pressure", _BLUE_ROOT)}
    if propulsion:
        permitted_constraints.update(("yellow_pressure_follows_measured_supply", root) for root in (_ENGINE_ROOT, _EDP_ROOT))
    exceptions = {}
    if generated:
        exceptions = {
            "inventory_before_pressure": _PRESSURE_ROOT,
            "generator_loss_with_drive_retained": _GEN_ROOT,
            "yellow_pump_loss_with_drive_retained": _EDP_ROOT,
        }
        permitted_constraints.update((name, _ENGINE_ROOT) for name in
                                     ("generator_loss_with_drive_retained", "yellow_pump_loss_with_drive_retained"))
    if (not isinstance(constraints, list) or any(not isinstance(item, dict)
            or (item.get("id"), item.get("root")) not in permitted_constraints
            or item.get("unless_root") != exceptions.get(item.get("id"))
            or not isinstance(item.get("reason"), str) for item in constraints)):
        raise ValueError("Unknown temporal constraint")


def _predictions(roots: list[str], model: dict) -> tuple[dict, list[dict]]:
    """Traverse declared dependencies; a conditional edge makes the path optional."""
    outgoing = {node["id"]: [] for node in model["nodes"]}
    for edge in model["edges"]:
        outgoing[edge["from"]].append(edge)
    reached: dict[str, list[dict]] = {fact: [] for fact in model["facts"]}
    paths = []

    def walk(node, path, reasons, conditional):
        for edge in outgoing[node]:
            target = edge["to"]
            next_conditional = conditional or edge["necessity"] == "conditional"
            entry = {
                "nodes": path + [target], "fact": target,
                "necessity": "conditional" if next_conditional else "required",
                "reason": " ".join(reasons + [edge["reason"]]),
            }
            if target in reached:
                reached[target].append(entry)
                paths.append(entry)
            walk(target, path + [target], reasons + [edge["reason"]], next_conditional)

    for root in roots:
        walk(root, [root], [], False)
    result = {}
    for fact in reached:
        entries = reached[fact]
        if any(entry["necessity"] == "required" for entry in entries):
            expected = "observed"
        elif entries:
            expected = "allowed"
        else:
            expected = "not_observed"
        result[fact] = {"fact": fact, "expected": expected, "dependency_paths": entries}
    return result, paths


def evaluate_hypotheses(frame: dict, *, temporal: bool = True, model: dict | None = None) -> dict:
    """Evaluate one feature frame without reading files, clocks or private labels.

    Status describes fit within a finite catalogue. Even a single compatible
    candidate does not establish a unique physical initiating cause.
    """
    if type(temporal) is not bool:
        raise ValueError("temporal must be a Boolean")
    selected_model = default_model() if model is None else copy.deepcopy(model)
    _validate_model(selected_model)
    generated = selected_model["model_id"] == V4_MODEL_ID
    fact_ids = tuple(selected_model["facts"])
    if not isinstance(frame, dict) or not isinstance(frame.get("facts"), dict) or set(frame["facts"]) != set(fact_ids):
        raise ValueError("A hypothesis frame requires exactly the facts selected by its model")
    facts = frame["facts"]
    for name, fact in facts.items():
        if (not isinstance(fact, dict) or fact.get("state") not in {"observed", "not_observed", "unknown"}
                or not isinstance(fact.get("evidence", []), list)):
            raise ValueError(f"Invalid selected fact: {name}")
    relations = frame.get("temporal_relations", {})
    if not isinstance(relations, dict):
        raise ValueError("temporal_relations must be an object")
    panels = []
    for definition in selected_model["candidates"]:
        predictions, paths = _predictions(definition["roots"], selected_model)
        supporting, contradicting, consequences, missing = [], [], [], []
        for name, prediction in predictions.items():
            fact, expected = facts[name], prediction["expected"]
            state = fact["state"]
            item = {
                "fact": name, "expected": expected, "observed_state": state,
                "evidence": copy.deepcopy(fact.get("evidence", [])),
                "dependency_paths": copy.deepcopy(prediction["dependency_paths"]),
            }
            if state == "unknown":
                item["status"] = "unconfirmed"
                item["reason"] = fact.get("reason", "Selected observation is unavailable or unconfirmed.")
                missing.append({
                    "fact": name,
                    "channels": list(fact.get("channels", selected_model["facts"][name]["channels"])),
                    "reason": item["reason"],
                    "could_test": "observed versus absent selected effect" if expected != "allowed" else "conditional downstream consequence",
                    "required_for_candidate_fit": expected != "allowed",
                })
            elif expected == "allowed":
                item["status"] = "consistent_conditional"
                item["reason"] = "This downstream effect is conditional; either retained or degraded output is compatible."
                supporting.append(copy.deepcopy(item))
            elif state == expected:
                item["status"] = "supported"
                item["reason"] = "Usable observation agrees with the executable dependency prediction."
                supporting.append(copy.deepcopy(item))
            else:
                item["status"] = "contradicted"
                item["reason"] = (
                    "The candidate requires this effect, but it is not observed in the supplied incident scope."
                    if expected == "observed" else
                    "This observed effect is not explained by the candidate's selected dependency paths."
                )
                contradicting.append(copy.deepcopy(item))
            consequences.append(item)
        temporal_items = []
        if temporal:
            checked = set()
            for constraint in selected_model["temporal_constraints"]:
                name = constraint["id"]
                if (constraint["root"] not in definition["roots"] or constraint.get("unless_root") in definition["roots"]
                        or name in checked):
                    continue
                checked.add(name)
                relation = relations.get(name, {})
                status = relation.get("status", "unknown")
                if status not in {"consistent", "contradicted", "unknown", "not_applicable"}:
                    raise ValueError("Invalid temporal relation status")
                item = {
                    "relation": constraint["id"], "status": status,
                    "reason": relation.get("reason", "Observable ordering is not established."),
                    "model_reason": constraint["reason"],
                    "evidence": copy.deepcopy(relation.get("evidence", [])),
                }
                temporal_items.append(item)
                if status == "contradicted":
                    contradicting.append(copy.deepcopy(item))
                elif status == "consistent":
                    supporting.append(copy.deepcopy(item))
        unconfirmed_required = [item for item in missing if item["required_for_candidate_fit"]]
        status = "contradicted" if contradicting else "unconfirmed" if unconfirmed_required else "compatible"
        panels.append({
            "id": definition["id"], "label": definition["label"],
            "kind": definition["kind"], "roots": list(definition["roots"]),
            "status": status, "scope_note": definition["scope_note"],
            "supporting_evidence": supporting, "contradicting_evidence": contradicting,
            "predicted_consequences": consequences, "dependency_paths": paths,
            "temporal_evidence": temporal_items, "missing_evidence": missing,
            "alternative_candidate_ids": [], "alternative_explanations": [],
            "cause_identifiable": False, "probabilities_computed": False,
        })
    compatible = [panel["id"] for panel in panels if panel["status"] == "compatible"]
    plausible = [panel["id"] for panel in panels if panel["status"] != "contradicted"]
    unknowns = [name for name in fact_ids if facts[name]["state"] == "unknown"]
    for panel in panels:
        alternatives = [other for other in panels if other["id"] != panel["id"] and other["id"] in plausible]
        panel["alternative_candidate_ids"] = [other["id"] for other in alternatives]
        panel["alternative_explanations"] = [{"id": other["id"], "label": other["label"], "status": other["status"]} for other in alternatives]
    fully_observed_normal = not unknowns and all(facts[name]["state"] == "not_observed" for name in fact_ids)
    if not plausible:
        status = "poor_model_fit"
    elif unknowns or not compatible:
        status = "insufficient_observations"
    elif fully_observed_normal and "selected_reference" in compatible:
        status = "no_selected_anomaly"
    elif len(compatible) > 1:
        status = "causal_ambiguity"
    else:
        status = "single_compatible_candidate"
    model_fit = "poor_fit" if not plausible else "fits" if compatible else "undetermined"
    joint_pairs = [pair for pair in [("independent_pair", "grouped_joint_event"),
                                   ("independent_pressure_pair", "grouped_pressure_joint_event"),
                                   ("independent_engine_blue_pressure_loss", "grouped_engine_blue_pressure_loss")]
                   if all(name in plausible for name in pair)]
    joint_tie = bool(joint_pairs)
    discriminators = []
    for joint_pair in joint_pairs:
        equivalent_history_note = {
            "candidate_ids": list(joint_pair),
            "available_measurements": [], "available_discriminator": False,
            "reason": "Both candidates have identical predicted effects and temporal rules across the selected observation model. No available modeled measurement can establish their initiating history.",
        }
        discriminators.append(equivalent_history_note)
        for panel in panels:
            if panel["id"] in equivalent_history_note["candidate_ids"]:
                panel["missing_evidence"].append(copy.deepcopy(equivalent_history_note))
    for name in unknowns:
        requirements = {}
        for panel in panels:
            if panel["id"] in plausible:
                prediction = next(item for item in panel["predicted_consequences"] if item["fact"] == name)
                requirements.setdefault(prediction["expected"], []).append(panel["id"])
        if len(requirements) > 1:
            discriminators.append({
                "fact": name, "available_measurements": list(selected_model["facts"][name]["channels"]),
                "available_discriminator": True, "candidate_partitions": requirements,
                "reason": "Restoring this selected measurement and its usable reference/progression could test different predicted effects. It cannot resolve equivalent initiating histories.",
            })
    result = {
        "schema_version": 1, "model_id": selected_model["model_id"],
        "mode": "temporal" if temporal else "atemporal", "status": status,
        "candidate_ids": compatible, "plausible_candidate_ids": plausible, "candidates": panels,
        "unique_candidate_within_catalogue": compatible[0] if len(compatible) == 1 else None,
        "cause_identifiable": False, "probabilities_computed": False,
        "data_sufficiency": {
            "status": "insufficient" if unknowns else "sufficient",
            "unknown_facts": unknowns,
            "scope": "Supplied selected incident/epoch facts; current observed impact is assessed separately.",
        },
        "model_fit": {"status": model_fit, "compatible_candidate_count": len(compatible), "plausible_candidate_count": len(plausible)},
        "ambiguity": {
            "status": "ambiguous" if len(compatible) > 1 else "unresolved_observations" if len(plausible) > 1 and not compatible else "not_established",
            "candidate_ids": compatible if len(compatible) > 1 else [],
            "equivalent_joint_histories": joint_tie,
        },
        "missing_evidence": discriminators,
        "model_assumptions": copy.deepcopy(selected_model["assumptions"]),
        "scope": copy.deepcopy(frame.get("scope", {})),
        "sample_index": frame.get("sample_index"), "epoch": frame.get("epoch"),
        "sim_time_s": frame.get("sim_time_s"),
    }
    if generated:
        matching_roots = {panel["id"]: set(panel["roots"]) for panel in panels if panel["id"] in compatible}
        minimal = [name for name, roots in matching_roots.items()
                   if not any(other < roots for other in matching_roots.values())]
        result["minimal_candidate_ids"] = minimal
        result["additional_compatible_ids"] = [name for name in compatible if name not in minimal]
        if status in ("single_compatible_candidate", "causal_ambiguity") and len(minimal) == 1:
            result["status"] = "one_minimal_explanation"
    return result
