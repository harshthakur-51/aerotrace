"""Format the public sequence diagnosis for the simulator pilot view."""


# A320 component abbreviations. These labels describe selected readings and
# mechanism classes. They do not assign ECAM alert levels or thresholds.
_EVENTS = {
    "generator_source_anomaly": "ELEC GEN 2 OUTPUT VOLTAGE LOW",
    "blue_inventory_loss": "HYD B RSVR QTY DECREASE",
    "bus_supply_loss": "ELEC AC BUS 2 SUPPLY DEGRADED",
    "blue_pressure_loss": "HYD B SYS LO PR",
    "engine_2_fuel_flow_loss": "ENG 2 FUEL FLOW LOW",
    "engine_2_core_speed_loss": "ENG 2 N2 LOW",
    "yellow_edp_output_loss": "HYD Y ENG 2 PUMP LO PR",
    "yellow_line_pressure_loss": "HYD Y SYS LO PR",
}
_CAUSES = {
    "engine_2_power_loss": "ENG 2 POWER LOSS",
    "generator_2_source_path_fault": "ELEC GEN 2 SOURCE PATH LOSS",
    "yellow_engine_driven_pump_supply_loss": "HYD Y ENG 2 PUMP LOCAL SUPPLY LOSS",
    "blue_pressure_supply_loss": "HYD B PRESSURE SUPPLY LOSS",
    "blue_fluid_loss_mechanism": "HYD B FLUID INVENTORY LOSS",
}
_MEASUREMENTS = {
    "engine_2_n2": "ENG 2 N2",
    "engine_2_fuel_flow": "ENG 2 FUEL FLOW",
    "generator_2_voltage": "ELEC GEN 2 VOLTAGE",
    "ac_bus_2": "ELEC AC BUS 2 VOLTAGE",
    "blue_quantity": "HYD B RSVR QTY",
    "blue_pressure": "HYD B SYS PR",
    "yellow_edp_pressure": "HYD Y ENG 2 PUMP PR",
    "yellow_pressure": "HYD Y SYS PR",
}


class GroundPowerClock:
    """Latch the first observed supply transition from a cold ground baseline."""

    def __init__(self):
        self._reset(None)

    def _reset(self, epoch):
        self.epoch = epoch
        self.origin = None
        self._off = None
        self._closed = False

    def observe(self, row, epoch):
        if epoch != self.epoch:
            self._reset(epoch)
        if self._closed:
            return
        readings = row["readings"]
        channel_names = ("external_power_output", "ac_bus_1", "ac_bus_2", "aircraft",
                         "main_gear_1_wow", "main_gear_2_wow", "sim_time", "paused")
        points = [readings.get(name) for name in channel_names]
        prior, self._off = self._off, None
        if not all(point and point["valid"] for point in points):
            if any(point and point["valid"] and point["value"] >= 110 for point in points[:3]):
                self._closed = True
            return
        external, bus_1, bus_2, aircraft, gear_1, gear_2, sim_time, paused = (point["value"] for point in points)
        if aircraft != "A320-200-CFM" or not (gear_1 and gear_2):
            self._closed = True
            return
        stamps = [sim_time, *(point["sim_time_s"] for point in points)]
        if paused or None in stamps or max(stamps) - min(stamps) > 0.25:
            self._closed = max(external, bus_1, bus_2) >= 110
            return
        sample = row["sample_index"]
        external_time = points[0]["sim_time_s"]
        if external >= 110:
            if prior and sample == prior[0] + 1 and 0 < external_time - prior[1] <= 3.0:
                self.origin = external_time
            self._closed = True
        elif 0 <= min(external, bus_1, bus_2) and max(external, bus_1, bus_2) < 5:
            self._off = (sample, external_time)
        elif max(bus_1, bus_2) >= 110:
            self._closed = True


def _timestamp(event_time, origin):
    if origin is None or event_time < origin:
        return "--:--:--"
    hours, remainder = divmod(int(event_time - origin), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def render_pilot_display(epoch, *, include_investigation=False):
    if epoch is None:
        return "AEROTRACE\n\nAwaiting airborne observations."
    events = sorted(
        ((fact["onset_interval"]["upper_sim_time_s"], _EVENTS[name])
         for name, fact in epoch["facts"].items() if fact["state"] == "observed"),
        key=lambda event: event[0],
    )
    origin = epoch.get("power_on_sim_s")
    column = max(map(len, _EVENTS.values())) + 4
    lines = ["AEROTRACE", "", f"{'EVENTS':<{column}}TIMESTAMPS"]
    if origin is not None:
        lines.append(f"{'ELEC EXT PWR SUPPLY ON':<{column}}00:00:00")
    lines.extend(f"{label:<{column}}{_timestamp(time, origin)}" for time, label in events)
    if not events:
        unknown = any(fact["state"] == "unknown" for fact in epoch["facts"].values())
        lines.append("Selected event evidence incomplete" if unknown else "No selected anomaly observed")
    lines.extend(("", "POSSIBLE EXPLANATIONS" if include_investigation else "CAUSE"))
    minimal = set(epoch["minimal_possible_mechanism_sets"])
    choices = [item for item in epoch["mechanism_sets"] if item["id"] in minimal]
    scores = []
    for index, choice in enumerate(choices, 1):
        causes = [label for root, label in _CAUSES.items() if root in choice["roots"]]
        if not causes:
            causes = ["No selected cause required" if choice["history_counts"]["compatible"] else "Unresolved"]
        prefix = f"{index}. " if len(choices) > 1 else ""
        lines.append(prefix + causes[0])
        lines.extend(("   " if prefix else "") + "+ " + cause for cause in causes[1:])
        support = choice["dependency_evidence_support"]
        percent = support["percent"]
        # Show the raw count: a bare "100%" reads as certainty about the cause.
        score = "--" if percent is None else f"{support['supported_checks']}/{support['total_checks']}"
        scores.append(f"{index}: {score}" if prefix else score)
    if not choices:
        lines.append("Unresolved")
    counts = epoch["history_counts"]
    lines.extend(("", f"{'C:U':<20}{counts['compatible']}:{counts['unconfirmed']}",
                  f"{'Checks matched':<20}{'  '.join(scores) or '--'}"))
    if include_investigation and "investigation" in epoch:
        lines.extend(_investigation_lines(epoch["investigation"]))
    return "\n".join(lines)


def _investigation_lines(investigation):
    evidence = investigation["evidence_selection"]
    lines = ["", "WHAT TO INVESTIGATE NEXT"]
    if evidence["recommended_measurements"]:
        channels = evidence["recommended_measurements"][0]["channels"]
        lines.append("Review " + " / ".join(_MEASUREMENTS[channel] for channel in channels))
    elif evidence["unavailable_discriminators"]:
        channels = dict.fromkeys(channel for item in evidence["unavailable_discriminators"]
                                 for channel in item["channels"])
        lines.append("Incident readings needed for " + " / ".join(_MEASUREMENTS[channel] for channel in channels))
        lines.append("The current capture cannot resolve the competing sets.")
    elif evidence["candidate_count"] > 1:
        lines.append("No modelled reading separates the remaining sets.")
    if investigation["observed_abnormalities"]:
        for item in investigation["masking"]["potentially_masked_mechanisms"]:
            status = ("Possibly masked" if any(candidate["status"] == "potentially_masked"
                                               for candidate in item["candidate_sets"]) else "Evidence missing")
            lines.append(f"{status:<18}{_CAUSES[item['mechanism']]}")
    common = investigation["common_cause"]
    if common["model_mismatch"]["status"] == "no_joint_model_fit":
        lines.append("Selected model has no joint fit.")
    elif any(cluster["unmodelled_common_cause_possible"] for cluster in common["clusters"]):
        lines.append("Common disturbance vs separate failures unresolved.")
    if len(lines) == 2:
        lines.append("No additional passive measurement ranked.")
    lines.extend(("", "Checks matched counts agreeing model checks per set; it is not a cause probability."))
    return lines
