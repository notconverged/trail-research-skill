import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from data_model import (  # noqa: E402
    DecisionPoint,
    EdgeDifficulty,
    EvidenceReference,
    RouteEdge,
    RouteNetwork,
    RouteNode,
    TrackSegmentObservation,
    TrailResearchData,
    VerificationState,
)
from route_network import (  # noqa: E402
    calculate_cutoff_time,
    estimate_edge_time,
    observed_times_for_edge,
    validate_route_network,
)


class RouteTimeTests(unittest.TestCase):
    def test_time_increases_with_climb_pack_and_team_penalty(self):
        easy_edge = RouteEdge(
            edge_id="E-1",
            distance_km=10,
            elevation_gain_m=200,
            difficulty=EdgeDifficulty(terrain_multiplier=1.0),
        )
        hard_edge = RouteEdge(
            edge_id="E-2",
            distance_km=10,
            elevation_gain_m=800,
            difficulty=EdgeDifficulty(
                technical_descent_m=400,
                terrain_multiplier=1.25,
            ),
        )
        easy = estimate_edge_time(easy_edge)
        hard = estimate_edge_time(
            hard_edge,
            pack_multiplier=1.15,
            team_multiplier=1.25,
            uncertainty_multiplier=1.10,
        )
        self.assertGreater(hard.planned_lower_hours, easy.planned_lower_hours)
        self.assertGreater(hard.planned_upper_hours, hard.planned_lower_hours)

    def test_observed_times_use_conservative_percentiles(self):
        edge = RouteEdge(
            edge_id="E-1",
            distance_km=5,
            difficulty=EdgeDifficulty(terrain_multiplier=1.0),
        )
        estimate = estimate_edge_time(
            edge,
            observed_moving_times=[1.0, 2.0, 3.0, 4.0, 5.0],
        )
        self.assertEqual(estimate.observed_p50_hours, 3.0)
        self.assertGreater(estimate.observed_p85_hours, estimate.observed_p50_hours)
        self.assertGreaterEqual(estimate.planned_upper_hours, estimate.observed_p85_hours)

    def test_cutoff_is_calculated_backwards(self):
        cutoff = calculate_cutoff_time(
            "18:30",
            remaining_p85_hours=3.5,
            fixed_buffer_minutes=30,
            contingency_buffer_minutes=30,
        )
        self.assertEqual(cutoff, "14:00")

    def test_whole_route_time_is_not_used_as_segment_observation(self):
        network = RouteNetwork(
            track_segment_observations=[
                TrackSegmentObservation(
                    observation_id="O-1",
                    track_id="T-1",
                    edge_id="E-1",
                    moving_time_hours=4.0,
                    split_method="whole-route",
                ),
                TrackSegmentObservation(
                    observation_id="O-2",
                    track_id="T-2",
                    edge_id="E-1",
                    moving_time_hours=2.0,
                    split_method="timestamped-gpx",
                ),
            ]
        )
        self.assertEqual(observed_times_for_edge(network, "E-1"), [2.0])


class RouteNetworkValidationTests(unittest.TestCase):
    def _network(self, bailout_status="Desk Verified"):
        evidence = [
            EvidenceReference(evidence_id="EV-1"),
            EvidenceReference(evidence_id="EV-2"),
        ]
        desk_state = VerificationState(
            verification_status=bailout_status,
            evidence_refs=["EV-1", "EV-2"] if bailout_status == "Desk Verified" else ["EV-1"],
        )
        return RouteNetwork(
            state=VerificationState(),
            nodes=[
                RouteNode(node_id="N-1"),
                RouteNode(node_id="N-2"),
            ],
            edges=[
                RouteEdge(
                    edge_id="E-B",
                    from_node="N-1",
                    to_node="N-2",
                    route_role="bailout",
                    state=desk_state,
                )
            ],
            decision_points=[
                DecisionPoint(
                    decision_id="DP-1",
                    node_id="N-1",
                    bailout_edge_ids=["E-B"],
                )
            ],
            evidence=evidence,
        )

    def test_candidate_bailout_cannot_be_used_operationally(self):
        errors = validate_route_network(self._network("Candidate"), operational=True)
        self.assertTrue(any("must be Desk Verified" in item for item in errors))

    def test_field_verified_requires_human_record(self):
        network = self._network()
        network.nodes[0].state = VerificationState(
            verification_status="Field Verified",
            evidence_refs=["EV-1"],
        )
        errors = validate_route_network(network)
        self.assertTrue(any("verified_at and verified_by" in item for item in errors))
        self.assertTrue(any("source_type 'field'" in item for item in errors))

    def test_old_json_loads_with_empty_route_network(self):
        old_payload = {
            "route": {
                "name": "旧路线",
                "total_distance_km": 12,
                "start_point": {"gps": "40.0, 116.0"},
                "end_point": {"gps": "40.1, 116.1"},
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "old.json"
            path.write_text(json.dumps(old_payload), encoding="utf-8")
            data = TrailResearchData.from_json(str(path))
        self.assertEqual(data.route.name, "旧路线")
        self.assertEqual(data.route_network.nodes, [])

    def test_route_network_round_trip_preserves_nested_types(self):
        original = TrailResearchData(route_network=self._network())
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "network.json"
            original.to_json(str(path))
            loaded = TrailResearchData.from_json(str(path))
        self.assertIsInstance(loaded.route_network.nodes[0].state, VerificationState)
        self.assertIsInstance(loaded.route_network.edges[0].difficulty, EdgeDifficulty)
        self.assertEqual(loaded.route_network.decision_points[0].decision_id, "DP-1")


if __name__ == "__main__":
    unittest.main()
