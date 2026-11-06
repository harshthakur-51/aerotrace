"""A late admission guard must execute after reads but before the native write."""
import time
import unittest
from unittest.mock import Mock,patch
from aircraft_debugger.flightgear import PropertyReading
from aircraft_debugger.sim_panel import PanelState,FAULT_PATHS

class PanelDeadlineTests(unittest.TestCase):
    def test_revoked_admission_after_prechecks_sends_no_http_request(self):
        client=Mock(host="127.0.0.1",port=8088,timeout_s=1)
        stamp=time.monotonic()
        client.read_property.side_effect=[
            PropertyReading("/sim/aircraft","A320-200-CFM",True,None,20,stamp,True),
            PropertyReading(FAULT_PATHS["generator_2"],False,True,None,20,stamp,True),
        ]
        def guard():
            self.assertEqual(client.read_property.call_count,2)
            raise RuntimeError("admission expired during prerequisite reads")
        with patch("aircraft_debugger.sim_panel.http.client.HTTPConnection") as connection:
            with self.assertRaisesRegex(RuntimeError,"admission expired"):
                PanelState(client).command({"fault":"generator_2","enabled":True},before_write_check=guard)
            connection.return_value.request.assert_not_called()
            connection.return_value.close.assert_called_once()
        self.assertEqual(client.read_property.call_count,2)

    def test_airborne_pinned_aircraft_cannot_switch_to_another_supported_variant(self):
        client=Mock(host="127.0.0.1",port=8088,timeout_s=1)
        client.read_property.return_value=PropertyReading("/sim/aircraft","A320neo-CFM",True,None,20,time.monotonic(),True)
        with patch("aircraft_debugger.sim_panel.http.client.HTTPConnection") as connection:
            status,_=PanelState(client).command({"fault":"generator_2","enabled":True},required_aircraft="A320-200-CFM")
            self.assertEqual(status,409)
            connection.assert_not_called()
        self.assertEqual(client.read_property.call_count,1)

if __name__=="__main__":unittest.main()
