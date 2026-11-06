"""Consistency failures that could mislead graph or evidence consumers."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aircraft_debugger.model import ModelDescriptorError, load_model_descriptor, validate_model_descriptor


class ModelDescriptorTests(unittest.TestCase):
    def setUp(self):
        self.model = json.loads(Path("configs/a320-diagnostic-model.json").read_text(encoding="utf-8"))

    def test_descriptor_is_read_only_and_native_feedback_is_not_a_diagnostic_cycle(self):
        original = copy.deepcopy(self.model)
        summary = validate_model_descriptor(self.model)
        self.assertEqual(self.model, original)
        self.assertEqual((summary["observations"], summary["private_inputs"], summary["target_faults"]), (12, 2, 8))
        self.assertEqual(summary["validation"], "descriptor_consistency_only")
        self.assertGreater(summary["native_couplings"], 0)

    def test_unit_change_and_private_property_alias_cannot_enter_the_observation_contract(self):
        for changes in ({"unit": "litres"}, {"path": "/systems/failures/hydraulic/blue-leak"}, {"name": "blue_leak"}):
            model = copy.deepcopy(self.model)
            model["observations"][-1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ModelDescriptorError):
                validate_model_descriptor(model)

    def test_dangling_nodes_sources_and_unknown_statuses_are_rejected(self):
        for key, value in (("to", "invented_bus"), ("source_ref", "unlisted_report"), ("status", "fully-certified")):
            model = copy.deepcopy(self.model)
            model["edges"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ModelDescriptorError):
                validate_model_descriptor(model)

    def test_a_diagnostic_feedback_cycle_is_rejected(self):
        edge = copy.deepcopy(self.model["edges"][0])
        edge["from"], edge["to"] = edge["to"], edge["from"]
        self.model["edges"].append(edge)
        with self.assertRaisesRegex(ModelDescriptorError, "cycle"):
            validate_model_descriptor(self.model)

    def test_duplicate_component_or_fault_identifiers_are_rejected(self):
        for key in ("nodes", "target_fault_catalogue"):
            model = copy.deepcopy(self.model)
            model[key][1]["id"] = model[key][0]["id"]
            with self.subTest(key=key), self.assertRaisesRegex(ModelDescriptorError, "duplicate"):
                validate_model_descriptor(model)

    def test_private_evidence_promotion_and_wrong_command_targets_are_rejected(self):
        for location in ("outer", "input", "target"):
            model = copy.deepcopy(self.model)
            private = model["private_control_descriptor"]
            if location == "outer":
                private["diagnostic_evidence"] = True
            elif location == "input":
                private["inputs"][0]["diagnostic_evidence"] = True
            else:
                private["inputs"][0]["target_node"] = "blue_inventory"
            with self.subTest(location=location), self.assertRaises(ModelDescriptorError):
                validate_model_descriptor(model)

    def test_declared_caps_and_recipe_source_reference_must_remain_consistent(self):
        for name, value in (("node_count_cap", 17), ("observation_count_cap", 11),
                            ("node_count_cap", True), ("observation_count_cap", True),
                            ("node_count_cap", 26), ("observation_count_cap", 21)):
            model = copy.deepcopy(self.model)
            model["boundaries"][name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ModelDescriptorError):
                validate_model_descriptor(model)
        self.model["private_control_descriptor"]["synthetic_regional_recipe"]["orchestration_source_ref"] = "unlisted_recipe"
        with self.assertRaisesRegex(ModelDescriptorError, "orchestration_source_ref"):
            validate_model_descriptor(self.model)

    def test_loader_reads_only_its_descriptor_and_allows_descriptive_recipe_metadata(self):
        self.model["private_control_descriptor"]["synthetic_regional_recipe"]["implementation_status"] = "working synthetic orchestration"
        Path("work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="work") as temporary:
            path = Path(temporary) / "model.json"
            path.write_text(json.dumps(self.model), encoding="utf-8")
            with patch.object(Path, "read_text", autospec=True, return_value=json.dumps(self.model)) as read:
                loaded = load_model_descriptor(path)
            self.assertEqual(loaded, self.model)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(read.call_args.args[0], path)


if __name__ == "__main__":
    unittest.main()
