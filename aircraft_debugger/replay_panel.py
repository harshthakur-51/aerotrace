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
    def __init__(self, records, *, temporal=True, model=None):
        self.token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._records = copy.deepcopy(list(records))
        self._model = default_model() if model is None else copy.deepcopy(model)
        self._frames = build_feature_frames(self._records, propulsion=uses_propulsion_profile(self._model),
                                            generated=self._model["model_id"] == V4_MODEL_ID)["frames"]
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
        return copy.deepcopy({
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
        })
