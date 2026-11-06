"""Read-only recorded-flight adapter for the existing local systems panel.

Frames are built from public prefixes only. Seeking never calls the simulator,
reads another file or supplies later observations to a selected frame.
"""

import copy
import secrets
import threading

from .diagnostic_features import build_feature_frames
from .hypotheses import V4_MODEL_ID, default_model, evaluate_hypotheses, uses_propulsion_profile


class ReplayPanelState:
    def __init__(self, records, *, temporal=True, model=None, pilot=False, response_bounds=None):
        self.token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._records = copy.deepcopy(list(records))
        self._model = default_model() if model is None else copy.deepcopy(model)
        generated = self._model["model_id"] == V4_MODEL_ID
        rows = self._records
        self._pilot_views = None
        if pilot:
            from .sequence_reasoning import _catalogue_orders, _response_bounds, _sequence_rows, pilot_text_for_epoch

            if not generated or not temporal:
                raise ValueError("The pilot view requires the temporal v4 model")
            _, rows = _sequence_rows(rows)
            bounds = _response_bounds(response_bounds, self._model)
            orders = _catalogue_orders(self._model)
        self._frames = build_feature_frames(rows, propulsion=uses_propulsion_profile(self._model),
                                            generated=generated, sequence_prefixes=pilot)["frames"]
        if pilot:
            self._pilot_views = [pilot_text_for_epoch(frame.pop("sequence_epoch"), self._model, orders, bounds)
                                 for frame in self._frames]
        if not self._frames:
            raise ValueError("Replay needs at least one public observation")
        self._diagnoses = [evaluate_hypotheses(frame, temporal=temporal, model=self._model)
                           for frame in self._frames]
        self._position = 0

    def seek(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {"position"}
                or type(payload["position"]) is not int
                or not 0 <= payload["position"] < len(self._frames)):
            raise ValueError("Expected one valid integer replay position")
        with self._lock:
            self._position = payload["position"]
        return 200, {"ok": True}

    def command(self, payload):
        return 409, {"ok": False, "error": "Recorded replay is read-only; simulator controls are disabled."}

    def get_state(self):
        with self._lock:
            position = self._position
        frame = self._frames[position]
        row = self._records[position]
        state = {
            "mode": "replay", "replay": {"position": position, "count": len(self._frames),
                "sample_index": row["sample_index"], "read_only": True},
            "telemetry": row, "poll_error": None, "poll_age_s": None,
            "oldest_reading_age_s": None, "poll_duration_s": None,
            "time_since_sim_advance_s": None, "operator_commands": {},
            "diagnosis": {"implemented": True, "result": self._diagnoses[position],
                "evidence": frame["facts"], "temporal_relations": frame["temporal_relations"],
                "current_impact": frame["current_impact"], "observed_impact": frame["observed_impact"],
                "model": self._model,
                "timeline": [{"sample_index": d["sample_index"], "sim_time_s": d["sim_time_s"],
                    "status": d["status"], "candidate_ids": d["candidate_ids"]}
                    for d in self._diagnoses[:position + 1]]},
        }
        if self._pilot_views is not None:
            state["pilot_view"] = True
            state["diagnosis"]["pilot_display"] = self._pilot_views[position]
        return copy.deepcopy(state)
