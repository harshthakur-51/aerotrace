"""Public propulsion and Yellow supply evidence for the bounded drive-loss study."""

PROPULSION_FACTS = {
    "engine_2_fuel_flow_loss": ("engine_2_fuel_flow", "Engine 2 fuel flow low"),
    "engine_2_core_speed_loss": ("engine_2_n2", "Engine 2 core speed low"),
    "yellow_edp_output_loss": ("yellow_edp_pressure", "Yellow engine-driven pump output reduced"),
    "yellow_line_pressure_loss": ("yellow_pressure", "Yellow line pressure low"),
}
PROPULSION_IMPACTS = {
    "engine_2_fuel_flow_loss": ("propulsion", "Engine 2 fuel flow fell below the study threshold.",
                                "The measured flow supports a power-loss pattern alongside core speed. Thrust is unmeasured."),
    "engine_2_core_speed_loss": ("propulsion", "Engine 2 core speed fell below the study threshold.",
                                 "Core speed is evidence of degraded engine drive. The initiating fault remains a hypothesis."),
    "yellow_edp_output_loss": ("hydraulic", "Yellow engine-driven pump output fell below the study threshold.",
                               "The electric pump or transfer from Green can sustain Yellow line pressure."),
    "yellow_line_pressure_loss": ("hydraulic", "Yellow line pressure fell below the study threshold.",
                                  "The pressure reading alone leaves actuator and aircraft capability unresolved."),
}

LOW_FUEL_FLOW_LB_H = 50.0
LOW_CORE_SPEED_PERCENT = 55.0
USEFUL_SOURCE_PSI = 2500.0
LOW_YELLOW_PRESSURE_PSI = 2000.0
INSUFFICIENT_SOURCE_PSI = 500.0
MINIMUM_YELLOW_QUANTITY_RAW = 1.0
SUPPLY_SETTLING_SIM_S = 6.0
MAXIMUM_READING_SKEW_SIM_S = 0.25
MAXIMUM_SUPPLY_GAP_SIM_S = 3.0
SUPPLY_CHANNELS = (
    "yellow_edp_pressure", "yellow_electric_pressure", "yellow_transfer_pressure",
    "yellow_quantity", "yellow_pressure",
)
_EFFECT_THRESHOLDS = {
    "engine_2_fuel_flow_loss": LOW_FUEL_FLOW_LB_H,
    "engine_2_core_speed_loss": LOW_CORE_SPEED_PERCENT,
    "yellow_edp_output_loss": USEFUL_SOURCE_PSI,
    "yellow_line_pressure_loss": LOW_YELLOW_PRESSURE_PSI,
}
_EVIDENCE_CHANNELS = tuple(dict.fromkeys([*(channel for channel, _ in PROPULSION_FACTS.values()), *SUPPLY_CHANNELS]))
_DRIVE_LOSSES = {
    "generator_loss_with_drive_retained": ("generator_2_voltage", 5.0),
    "yellow_pump_loss_with_drive_retained": ("yellow_edp_pressure", INSUFFICIENT_SOURCE_PSI),
}
_RETAINED_DRIVE_LEVELS = {"engine_2_n2": 60.0, "engine_2_fuel_flow": 100.0}


def add_propulsion_evidence(snapshot, context, *, generated=False):
    """Enrich one feature snapshot using quality-checked, timestamped readings."""
    airborne = (
        context["aircraft"]["value"] == "A320-200-CFM"
        and context["main_gear_1_wow"]["value"] is False
        and context["main_gear_2_wow"]["value"] is False
        and context["height_agl"]["value"] is not None
        and context["height_agl"]["value"] > 0
    )
    points = {}
    channels = (*_EVIDENCE_CHANNELS, "generator_2_voltage") if generated else _EVIDENCE_CHANNELS
    for channel in channels:
        reading = context[channel]
        if not airborne or not reading["current_usable"] or reading["value"] < 0:
            continue
        points[channel] = {
            "channel": channel, "sample_index": snapshot["sample_index"],
            "sim_time_s": reading["sim_time_s"], "value": reading["value"], "unit": reading["unit"],
        }

    for name, (channel, _) in PROPULSION_FACTS.items():
        point = points.get(channel)
        decision = "unknown"
        if point is not None:
            decision = "observed" if point["value"] < _EFFECT_THRESHOLDS[name] else "not_observed"
            point = {**point, "observed_status": decision, "evidence_id": None}
        snapshot["facts"][name] = decision
        snapshot["usable"][name] = point is not None
        snapshot["soft_reference"][name] = False
        snapshot["points"][name] = point
        if decision == "observed":
            system, observation, remaining = PROPULSION_IMPACTS[name]
            snapshot["impact"].append({
                "fact_id": name, "system": system, "observation": observation,
                "remaining_capability": remaining, "evidence": [point],
            })

    snapshot["propulsion_supply"] = {name: points[name] for name in SUPPLY_CHANNELS if name in points}
    if generated:
        snapshot["drive_witnesses"] = _retained_drive_witnesses(points)


def _retained_drive_witnesses(points):
    if any(name not in points or points[name]["value"] < minimum
           for name, minimum in _RETAINED_DRIVE_LEVELS.items()):
        return {}
    witnesses = {}
    for relation, (channel, loss_threshold) in _DRIVE_LOSSES.items():
        if channel not in points or points[channel]["value"] >= loss_threshold:
            continue
        readings = [points[name] for name in (*_RETAINED_DRIVE_LEVELS, channel)]
        times = [point["sim_time_s"] for point in readings]
        if max(times) - min(times) <= MAXIMUM_READING_SKEW_SIM_S:
            witnesses[relation] = readings
    return witnesses


def retained_drive_relations(window):
    """A sustained source loss with drive retained needs a separate path."""
    results = {}
    for name in _DRIVE_LOSSES:
        results[name] = {"status": "not_applicable",
                         "reason": "A sustained source loss with retained engine drive remains unconfirmed.", "evidence": []}
        for previous, current in zip(window, window[1:]):
            before = previous["drive_witnesses"].get(name)
            after = current["drive_witnesses"].get(name)
            if (before and after and current["sample_index"] == previous["sample_index"] + 1
                    and all(0 < right["sim_time_s"] - left["sim_time_s"] <= MAXIMUM_SUPPLY_GAP_SIM_S
                            for left, right in zip(before, after))):
                results[name] = {"status": "contradicted",
                                 "reason": "Two consecutive polls show source loss while measured core speed and fuel flow remain available.",
                                 "evidence": before + after}
                break
    return results


def _backup_condition(points):
    if points.keys() != set(SUPPLY_CHANNELS):
        return None
    times = [point["sim_time_s"] for point in points.values()]
    if max(times) - min(times) > MAXIMUM_READING_SKEW_SIM_S:
        return None
    if (points["yellow_edp_pressure"]["value"] >= INSUFFICIENT_SOURCE_PSI
            or points["yellow_quantity"]["value"] < MINIMUM_YELLOW_QUANTITY_RAW):
        return None
    alternate = max(points[name]["value"] for name in ("yellow_electric_pressure", "yellow_transfer_pressure"))
    if alternate >= USEFUL_SOURCE_PSI:
        return "supported by alternate supply"
    if alternate < INSUFFICIENT_SOURCE_PSI:
        return "without measured backup"
    return None


def yellow_supply_relation(facts, window):
    """Test settled line pressure against the observed primary and backup supplies."""
    if facts["yellow_edp_output_loss"]["state"] != "observed":
        return {"status": "not_applicable", "reason": "Yellow pump output loss is unconfirmed.", "evidence": []}
    matches = {}
    previous_mode, previous_points, previous_index, first_points = None, {}, None, {}
    for snapshot in window:
        points = snapshot["propulsion_supply"]
        mode = _backup_condition(points)
        index = snapshot["sample_index"]
        continuous = (mode is not None and mode == previous_mode and index == previous_index + 1
                      and all(0 < points[name]["sim_time_s"] - previous_points[name]["sim_time_s"]
                              <= MAXIMUM_SUPPLY_GAP_SIM_S for name in SUPPLY_CHANNELS))
        if not continuous:
            first_points = points
        previous_mode, previous_points, previous_index = mode, points, index
        if mode is None or min(points[name]["sim_time_s"] - first_points[name]["sim_time_s"]
                               for name in SUPPLY_CHANNELS) < SUPPLY_SETTLING_SIM_S:
            continue
        line = points["yellow_pressure"]["value"]
        if LOW_YELLOW_PRESSURE_PSI <= line < USEFUL_SOURCE_PSI:
            continue
        retained = line >= USEFUL_SOURCE_PSI
        expected_retained = mode == "supported by alternate supply"
        evidence = [points[name] for name in SUPPLY_CHANNELS]
        expected = "retained" if expected_retained else "low"
        if retained != expected_retained:
            return {"status": "contradicted", "reason": f"Settled Yellow line pressure disagrees with the expected {expected} state {mode}.",
                    "evidence": evidence}
        matches.setdefault(mode, evidence)
    if matches:
        return {"status": "consistent", "reason": "Settled Yellow line pressure agrees with the measured supply condition "
                + " and ".join(matches) + ".", "evidence": [point for group in matches.values() for point in group]}
    return {"status": "unknown", "reason": "The observed pressure and inventory readings did not establish a settled Yellow supply condition.",
            "evidence": []}
