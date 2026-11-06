"""Read-only consistency checks for the scoped mechanism descriptor.

Checks references, declared boundaries and agreement with executable allowlists.
Passing does not verify source claims, likelihoods, geometry or aircraft behaviour.
Only the explicitly named JSON file is read; native assets are not required.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from .observations import CHANNELS
from .sim_panel import FAULT_PATHS

# The historical descriptor audits exactly its two declared interventions.
# Later operator capabilities do not retroactively change that descriptor.
_DESCRIPTOR_V1_PATHS = {name: FAULT_PATHS[name] for name in ("generator_2", "blue_leak")}


EDGE_TYPES = frozenset({
    "functional_drive", "conditional_supply", "functional_supply",
    "conditional_supply_route_abstraction", "conditional_alternate_supply",
    "conditional_electric_supply", "conditional_pressure_supply",
    "conditional_alternate_pressure", "inventory_support",
    "conditional_pressure_drive", "conditional_electric_alternate",
    "conditional_actuator_support", "physical_exposure_assumption",
    "synthetic_to_native_damage_proxy",
})


class ModelDescriptorError(ValueError):
    """The descriptor disagrees with its declared graph or public/private boundary."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ModelDescriptorError(message)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _known(value: object, choices: object) -> bool:
    return isinstance(value, str) and value in choices


def _index(items: object, key: str, label: str) -> dict:
    _check(isinstance(items, list), f"{label} must be a list")
    result = {}
    for item in items:
        _check(isinstance(item, dict) and _text(item.get(key)), f"{label} entries need a text {key}")
        _check(item[key] not in result, f"{label} has duplicate {key}: {item[key]}")
        result[item[key]] = item
    return result


def validate_model_descriptor(descriptor: dict) -> dict:
    """Return counts for a consistent descriptor; raise ModelDescriptorError otherwise.

    Extra descriptive metadata is allowed. Source references are checked against
    this descriptor, without opening source files or private intervention history.
    Native feedback couplings are checked separately and are not diagnostic edges.
    """
    _check(isinstance(descriptor, dict), "model descriptor must be an object")
    _check(type(descriptor.get("schema_version")) is int and descriptor["schema_version"] == 1, "schema_version must be integer 1")
    _check(_text(descriptor.get("model_id")), "model_id must be nonempty text")
    statuses, sources = descriptor.get("status_definitions"), descriptor.get("provenance")
    _check(isinstance(statuses, dict) and bool(statuses) and all(_text(k) and _text(v) for k, v in statuses.items()), "status_definitions must define named statuses")
    _check(isinstance(sources, dict) and bool(sources) and all(_text(k) and isinstance(v, dict) and _text(v.get("local_path")) for k, v in sources.items()), "provenance must define named local source paths")

    def references(item: dict, label: str, *, plural: bool = True) -> None:
        refs = item.get("source_refs") if plural else [item.get("source_ref")]
        _check(isinstance(refs, list) and bool(refs) and all(isinstance(ref, str) and ref in sources for ref in refs), f"{label} has missing or unknown source references")
        if "recorded_outcome_ref" in item:
            _check(_known(item["recorded_outcome_ref"], sources), f"{label} has an unknown recorded_outcome_ref")

    nodes = _index(descriptor.get("nodes"), "id", "nodes")
    _check(1 <= len(nodes) <= 25, "nodes must contain 1 to 25 unique identifiers")
    observations = _index(descriptor.get("observations"), "name", "observations")
    _check(observations.keys() == CHANNELS.keys(), "observations must match the exact twelve canonical channel names")
    for name, node in nodes.items():
        _check(node.get("read_only") is True and _text(node.get("kind")), f"node {name} must be typed and read_only=true")
        references(node, f"node {name}")
        linked = node.get("observations")
        _check(isinstance(linked, list) and all(isinstance(channel, str) and channel in observations and observations[channel].get("node_id") == name for channel in linked), f"node {name} has invalid observation references")
    for name, observation in observations.items():
        spec, node_id = CHANNELS[name], observation.get("node_id")
        _check((observation.get("path"), observation.get("kind"), observation.get("unit")) == (spec.path, spec.kind, spec.unit), f"observation {name} path/kind/unit differs from the canonical contract")
        _check(observation.get("read_only") is True, f"observation {name} must be read_only=true")
        _check((node_id is None) == (name in {"aircraft", "sim_time", "paused", "altitude", "airspeed"}), f"observation {name} must preserve its context or measured-node role")
        _check(node_id is None or isinstance(node_id, str) and node_id in nodes and name in nodes[node_id]["observations"], f"observation {name} has an invalid node_id")
        if "source_refs" in observation:
            references(observation, f"observation {name}")
    boundaries = descriptor.get("boundaries", {})
    _check(isinstance(boundaries, dict) and boundaries.get("descriptor_writes_native_state") is False and boundaries.get("private_controls_are_diagnostic_evidence") is False, "descriptor must preserve read-only and private-evidence boundaries")
    for name, count, limit in (("node_count_cap", len(nodes), 25), ("observation_count_cap", len(observations), 20)):
        cap = boundaries.get(name)
        _check(type(cap) is int and 1 <= cap <= limit and count <= cap, f"{name} must be an integer within the project limit and cover the actual count")
    edges = descriptor.get("edges")
    _check(isinstance(edges, list), "edges must be a list")
    for edge in edges:
        _check(isinstance(edge, dict) and isinstance(edge.get("from"), str) and edge["from"] in nodes and isinstance(edge.get("to"), str) and edge["to"] in nodes, "edge has a dangling node reference")
        _check(_known(edge.get("type"), EDGE_TYPES) and _known(edge.get("status"), statuses), "edge needs a known type and defined status")
        references(edge, "edge", plural=False)
    remaining = set(nodes)
    while remaining:
        roots = {node for node in remaining if not any(edge["to"] == node and edge["from"] in remaining for edge in edges)}
        _check(bool(roots), "diagnostic edge graph contains a cycle")
        remaining -= roots
    couplings = descriptor.get("native_couplings_outside_diagnostic_dag", [])
    _check(isinstance(couplings, list), "native couplings must be a list")
    for coupling in couplings:
        _check(isinstance(coupling, dict) and isinstance(coupling.get("nodes"), list) and all(isinstance(node, str) and node in nodes for node in coupling["nodes"]) and len(set(coupling["nodes"])) >= 2, "native coupling has invalid node references")
        _check(_known(coupling.get("status"), statuses), "native coupling has an undefined status")
        references(coupling, "native coupling", plural=False)
    private = descriptor.get("private_control_descriptor")
    _check(isinstance(private, dict) and private.get("diagnostic_evidence") is False, "private controls must have diagnostic_evidence=false")
    inputs = _index(private.get("inputs"), "command_name", "private inputs")
    _check(inputs.keys() == _DESCRIPTOR_V1_PATHS.keys(), "private inputs must match the exact two executable commands")
    for name, item in inputs.items():
        _check(item.get("path") == FAULT_PATHS[name] and item.get("kind") == "bool" and item.get("enabled_value") is True and item.get("disabled_value") is False, f"private input {name} differs from its native boolean command")
        _check(item.get("target_node") == {"generator_2": "generator_2", "blue_leak": "blue_inventory"}[name] and item["target_node"] in nodes, f"private input {name} has an invalid target_node")
        _check(_known(item.get("status"), statuses) and item.get("diagnostic_evidence", False) is False, f"private input {name} has an undefined status or promotes private evidence")
        references(item, f"private input {name}")
    recipe = private.get("synthetic_regional_recipe")
    _check(isinstance(recipe, dict) and _known(recipe.get("status"), statuses) and isinstance(recipe.get("requested_inputs"), list) and all(isinstance(name, str) for name in recipe["requested_inputs"]) and set(recipe["requested_inputs"]) == set(inputs), "synthetic recipe needs a defined status and the two known inputs")
    if "orchestration_source_ref" in recipe:
        _check(_known(recipe["orchestration_source_ref"], sources), "synthetic recipe has an unknown orchestration_source_ref")
    targets = _index(descriptor.get("target_fault_catalogue"), "id", "target fault catalogue")
    _check(set(targets) == {f"F{number}" for number in range(1, 9)}, "target fault catalogue must preserve exactly F1 through F8")
    for name, item in targets.items():
        _check(_known(item.get("status"), statuses) and ("control_name" not in item or _known(item["control_name"], inputs)), f"target {name} has an undefined status or private control reference")
        references(item, f"target {name}")
    return {"model_id": descriptor["model_id"], "validation": "descriptor_consistency_only", "nodes": len(nodes), "diagnostic_edges": len(edges), "native_couplings": len(couplings), "observations": len(observations), "private_inputs": len(inputs), "target_faults": len(targets), "target_status_counts": dict(Counter(item["status"] for item in targets.values()))}


def load_model_descriptor(path: Path) -> dict:
    """Read and validate the named JSON file without following its source paths."""
    descriptor = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_model_descriptor(descriptor)
    return descriptor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(validate_model_descriptor(load_model_descriptor(args.model)), indent=2))
    except (ModelDescriptorError, OSError, ValueError) as error:
        parser.exit(1, f"Model descriptor invalid: {error}\n")


if __name__ == "__main__":
    main()
