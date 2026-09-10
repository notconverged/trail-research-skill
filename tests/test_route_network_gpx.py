import sys
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from data_model import (  # noqa: E402
    CoordinateInfo,
    CutoffPoint,
    DecisionPoint,
    GeoPoint,
    ImageEvidence,
    RouteEdge,
    RouteNetwork,
    RouteNode,
    TimeEstimate,
    TrackSource,
    TrailResearchData,
)
from route_network_gpx import GPX_NS, TR_NS, export_route_network_gpx, ordered_sources  # noqa: E402


class RouteNetworkGpxTests(unittest.TestCase):
    def _data(self):
        nodes = [
            RouteNode(node_id="N1", name="起点", node_types=["start"], coordinate=CoordinateInfo(gps="40.0000,116.0000")),
            RouteNode(node_id="N2", name="山脊岔口", node_types=["junction"], coordinate=CoordinateInfo(gps="40.0100,116.0100"), field_identification="石墙缺口", signal_summary="弱"),
            RouteNode(node_id="N3", name="终点", node_types=["end"], coordinate=CoordinateInfo(gps="40.0200,116.0200")),
            RouteNode(node_id="N4", name="下撤公路", node_types=["vehicle"], coordinate=CoordinateInfo(gps="40.0050,116.0300")),
        ]
        sources = [
            TrackSource(track_id="WIKI-NEW", platform="Wikiloc", recorded_at="2026-09-01", url="https://example.com/wiki"),
            TrackSource(track_id="2B-OLD", platform="两步路", recorded_at="2025-09-01", url="https://example.com/old"),
            TrackSource(track_id="2B-NEW", platform="2bulu", recorded_at="2026-08-01", url="https://example.com/new"),
        ]
        main1 = RouteEdge(
            edge_id="E1", from_node="N1", to_node="N2", name="起点至岔口", route_role="main", gpx_route_id="MAIN",
            distance_km=2, elevation_gain_m=300, condition_summary="清晰土路，末段陡升",
            time_estimate=TimeEstimate(planned_lower_hours=1.2, planned_upper_hours=1.8),
            track_source_ids=["WIKI-NEW", "2B-OLD", "2B-NEW"],
            geometry_points=[GeoPoint(40, 116, 1000), GeoPoint(40.01, 116.01, 1300)],
        )
        main2 = RouteEdge(
            edge_id="E2", from_node="N2", to_node="N3", name="岔口至终点", route_role="main", gpx_route_id="MAIN",
            distance_km=3, elevation_loss_m=500, condition_summary="碎石下降",
            time_estimate=TimeEstimate(planned_lower_hours=1.5, planned_upper_hours=2.2),
            track_source_ids=["2B-NEW"],
            geometry_points=[GeoPoint(40.01, 116.01, 1300), GeoPoint(40.02, 116.02, 800)],
        )
        bailout = RouteEdge(
            edge_id="EB1", from_node="N2", to_node="N4", name="岔口下撤公路", route_role="bailout", gpx_route_id="BAILOUT-A",
            distance_km=2.5, elevation_loss_m=400, condition_summary="林间支路，雨后泥泞",
            time_estimate=TimeEstimate(planned_lower_hours=1.0, planned_upper_hours=1.6),
            track_source_ids=["2B-OLD"],
            geometry_points=[GeoPoint(40.01, 116.01, 1300), GeoPoint(40.005, 116.03, 900)],
        )
        decision = DecisionPoint(
            decision_id="DP1", node_id="N2", main_edge_ids=["E2"], bailout_edge_ids=["EB1"],
            planned_arrival_window="11:30–12:15", trigger_conditions=["晚于截止时间", "雷雨"], decision_action="全队下撤",
        )
        cutoff = CutoffPoint(
            cutoff_id="CP1", decision_point_id="DP1", cutoff_time="12:30", safe_arrival_deadline="16:30",
            remaining_p85_hours=2.8, action_after_cutoff="进入EB1下撤",
        )
        image = ImageEvidence(
            image_id="IMG1", node_id="N2", source_platform="两步路", track_source_id="2B-NEW",
            source_url="https://example.com/2bulu-note", direct_image_url="https://example.com/photo.jpg",
        )
        return TrailResearchData(route_network=RouteNetwork(
            name="测试路网", nodes=nodes, edges=[main1, main2, bailout], track_sources=sources,
            decision_points=[decision], cutoff_points=[cutoff], image_evidence=[image],
        ))

    def test_source_priority_is_two_steps_then_date_then_external(self):
        ordered = ordered_sources(self._data().route_network.track_sources)
        self.assertEqual([item.track_id for item in ordered], ["2B-NEW", "2B-OLD", "WIKI-NEW"])

    def test_export_contains_main_bailout_decision_conditions_and_photo(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "network.gpx"
            result = export_route_network_gpx(self._data(), output)
            root = ET.parse(output).getroot()
            ns = {"g": GPX_NS, "tr": TR_NS}
            self.assertEqual(result["main_track_count"], 1)
            self.assertEqual(result["bailout_track_count"], 1)
            self.assertEqual(len(root.findall("g:trk", ns)), 2)
            names = [item.text for item in root.findall("g:wpt/g:name", ns)]
            self.assertTrue(any("DP DP1 / CP 12:30" in item for item in names))
            descriptions = [item.text for item in root.findall("g:wpt/g:desc", ns)]
            self.assertTrue(any("计划到达：11:30–12:15" in item for item in descriptions))
            self.assertTrue(any("下撤：EB1" in item for item in descriptions))
            conditions = [item.text for item in root.findall(".//tr:condition_summary", ns)]
            self.assertIn("林间支路，雨后泥泞", conditions)
            links = root.findall("g:wpt/g:link", ns)
            self.assertEqual(links[0].attrib["href"], "https://example.com/photo.jpg")
            source_entries = root.findall("g:metadata/g:extensions/tr:source", ns)
            self.assertEqual([item.attrib["track_id"] for item in source_entries], ["2B-NEW", "2B-OLD", "WIKI-NEW"])

    def test_missing_bailout_geometry_is_a_hard_error(self):
        data = self._data()
        data.route_network.edges[-1].geometry_points = []
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "needs at least 2 geometry_points"):
                export_route_network_gpx(data, Path(temp) / "network.gpx")

    def test_geometry_points_survive_json_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "network.json"
            self._data().to_json(str(path))
            loaded = TrailResearchData.from_json(str(path))
            point = loaded.route_network.edges[0].geometry_points[0]
            self.assertIsInstance(point, GeoPoint)
            self.assertEqual((point.lat, point.lon), (40, 116))


if __name__ == "__main__":
    unittest.main()
