"""Count the model checks backed by observations for a diagnostic candidate."""


def evidence_support(candidate, additional_timing_checks=()):
    """Describe evidence coverage. A hard contradiction excludes the candidate."""
    states = [item["status"] for item in candidate["predicted_consequences"]
              if item["expected"] != "allowed"]
    for check in [*candidate["temporal_evidence"], *additional_timing_checks]:
        state = check["status"]
        if state != "not_applicable":
            states.append({"consistent": "supported", "unknown": "unconfirmed"}.get(state, state))
    supported = states.count("supported")
    contradicted = states.count("contradicted")
    return {
        "percent": round(100 * supported / len(states)) if states and not contradicted else None,
        "supported_checks": supported,
        "total_checks": len(states),
        "unconfirmed_checks": states.count("unconfirmed"),
        "contradicted_checks": contradicted,
    }
