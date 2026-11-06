"""Bounded observation-only session for causal updates, with no I/O.

Feature aggregation and airborne context advance once per poll. The shared
selected-system detector still evaluates its projected prefix on each update.
The limit stops inference explicitly and preserves history.
"""

import copy

from .airborne_evidence import _ContextHistory, _shared_core_record
from .airborne_profile import validate_airborne_observation, validate_propulsion_observation
from .diagnostic_features import FeatureHistory
from .evidence import analyze_observations
from .hypotheses import V4_MODEL_ID, default_model, evaluate_hypotheses, uses_propulsion_profile
from .observations import ObservationFormatError


class SessionLimitReached(RuntimeError):
    pass


class DiagnosisSession:
    def __init__(self, *, temporal=True, max_records=1200, model=None):
        if type(temporal) is not bool:
            raise ValueError("temporal must be Boolean")
        if type(max_records) is not int or not 1 <= max_records <= 1200:
            raise ValueError("max_records must be an integer from 1 to 1200")
        self.temporal = temporal
        self.max_records = max_records
        self._selected_records = []
        self._model = default_model() if model is None else copy.deepcopy(model)
        self._propulsion = uses_propulsion_profile(self._model)
        self._airborne_context = _ContextHistory(propulsion=self._propulsion)
        self._history = FeatureHistory(propulsion=self._propulsion, generated=self._model["model_id"] == V4_MODEL_ID)
        self._timeline = []
        self._version = None

    @property
    def count(self):
        return len(self._selected_records)

    def advance(self, record):
        if self.count >= self.max_records:
            raise SessionLimitReached("Diagnosis session limit reached; restart the panel for a new explicit session. Earlier history was not dropped.")
        row = copy.deepcopy(record)
        if not isinstance(row, dict) or type(row.get("schema_version")) is not int:
            raise ObservationFormatError("Public observation schema required")
        version = row["schema_version"]
        supported = (3,) if self._propulsion else (1, 2)
        if version not in supported or (self._version is not None and version != self._version):
            raise ObservationFormatError("Homogeneous observations matching the selected catalogue are required")
        selected = row
        if version != 1:
            validator = validate_propulsion_observation if self._propulsion else validate_airborne_observation
            selected = _shared_core_record(validator(row))
        # Check the shared detector's full prefix before advancing any live context.
        report = analyze_observations(self._selected_records + [selected])
        if version != 1:
            # Reuse the offline context tracker and retain every full public row.
            # The replay file digest and full context export are offline outputs.
            self._airborne_context.add(row)
            report["airborne_context"] = {"quality": self._airborne_context.quality,
                                          "latest_channels": self._airborne_context.latest_channels}
        frame = self._history.advance(row, report)
        result = evaluate_hypotheses(frame, temporal=self.temporal, model=self._model)
        self._selected_records.append(selected)
        self._version = version
        self._timeline.append({"sample_index": frame["sample_index"],
            "sim_time_s": frame["sim_time_s"], "status": result["status"],
            "candidate_ids": result["candidate_ids"]})
        return copy.deepcopy({"implemented": True, "result": result,
            "evidence": frame["facts"], "temporal_relations": frame["temporal_relations"],
            "current_impact": frame["current_impact"], "observed_impact": frame["observed_impact"],
            "current_quality": frame["current_quality"], "model": self._model,
            "timeline": self._timeline,
            "session": {"record_count": self.count, "max_records": self.max_records,
                "history_policy": "Retain every accepted public poll; stop inference at limit without truncation."}})
