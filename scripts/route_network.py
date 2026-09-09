"""Deterministic helpers for route-network research.

The research agent collects evidence and assigns candidate states. This module
only performs reproducible time calculations and structural validation; it does
not promote online evidence to Field Verified.
"""

from datetime import datetime, timedelta
from math import ceil, floor
from typing import Iterable, Optional

from data_model import RouteEdge, RouteNetwork, TeamProfile, TimeEstimate, TrailResearchData


VERIFICATION_RANK = {
    "Candidate": 0,
    "Desk Verified": 1,
    "Field Verified": 2,
}
AVAILABILITY_STATUSES = {"Open", "Restricted", "Closed", "Unknown"}


def _percentile(values: Iterable[float], percentile: float) -> float:
    """Return a linearly interpolated percentile without third-party packages."""
    ordered = sorted(float(value) for value in values if float(value) > 0)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower_index = floor(position)
    upper_index = ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] + (
        ordered[upper_index] - ordered[lower_index]
    ) * fraction


def estimate_edge_time(
    edge: RouteEdge,
    *,
    base_speed_kmh: float = 2.5,
    ascent_rate_m_per_hour: float = 450.0,
    descent_rate_m_per_hour: float = 700.0,
    pack_multiplier: float = 1.0,
    team_multiplier: float = 1.0,
    uncertainty_multiplier: Optional[float] = None,
    observed_moving_times: Iterable[float] = (),
    observed_adjustment: float = 1.0,
) -> TimeEstimate:
    """Estimate a conservative interval for one edge.

    Distance time uses the requested 2.5 km/h ordinary-team baseline. Ascent
    and technical descent are added separately. Two-step/GPX observations form
    an independent lower/upper envelope; fastest records are never used.
    """
    if uncertainty_multiplier is None:
        uncertainty_multiplier = {
            "Candidate": 1.20,
            "Desk Verified": 1.10,
            "Field Verified": 1.02,
        }.get(edge.state.verification_status, 1.20)

    positive_inputs = {
        "base_speed_kmh": base_speed_kmh,
        "ascent_rate_m_per_hour": ascent_rate_m_per_hour,
        "descent_rate_m_per_hour": descent_rate_m_per_hour,
        "pack_multiplier": pack_multiplier,
        "team_multiplier": team_multiplier,
        "uncertainty_multiplier": uncertainty_multiplier,
        "observed_adjustment": observed_adjustment,
    }
    for name, value in positive_inputs.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")
    if (
        edge.distance_km < 0
        or edge.elevation_gain_m < 0
        or edge.difficulty.technical_descent_m < 0
    ):
        raise ValueError("distance, elevation gain, and technical descent cannot be negative")
    if edge.difficulty.terrain_multiplier <= 0:
        raise ValueError("terrain_multiplier must be greater than zero")

    distance_hours = edge.distance_km / base_speed_kmh
    ascent_hours = edge.elevation_gain_m / ascent_rate_m_per_hour
    descent_hours = (
        edge.difficulty.technical_descent_m / descent_rate_m_per_hour
    )
    baseline = distance_hours + ascent_hours + descent_hours
    model_core = (
        baseline
        * edge.difficulty.terrain_multiplier
        * pack_multiplier
        * team_multiplier
    )
    model_lower = model_core * 0.90
    model_upper = model_core * 1.10 * uncertainty_multiplier

    observations = [float(value) for value in observed_moving_times if float(value) > 0]
    observed_p50 = _percentile(observations, 0.50)
    observed_p85 = _percentile(observations, 0.85)
    if observations:
        planned_lower = max(model_lower, observed_p50 * observed_adjustment)
        planned_upper = max(
            model_upper,
            observed_p85 * observed_adjustment * uncertainty_multiplier,
        )
    else:
        planned_lower = model_lower
        planned_upper = model_upper

    return TimeEstimate(
        baseline_hours=round(baseline, 2),
        model_lower_hours=round(model_lower, 2),
        model_upper_hours=round(model_upper, 2),
        observed_p50_hours=round(observed_p50, 2),
        observed_p85_hours=round(observed_p85, 2),
        planned_lower_hours=round(planned_lower, 2),
        planned_upper_hours=round(planned_upper, 2),
        base_speed_kmh=base_speed_kmh,
        ascent_rate_m_per_hour=ascent_rate_m_per_hour,
        descent_rate_m_per_hour=descent_rate_m_per_hour,
        pack_multiplier=pack_multiplier,
        team_multiplier=team_multiplier,
        uncertainty_multiplier=uncertainty_multiplier,
        notes=[
            "Observed values use P50-P85 moving time; total elapsed time is not mixed in.",
            "The planned interval is the conservative envelope of model and observations.",
        ],
    )


def estimate_edge_time_for_profile(
    edge: RouteEdge,
    profile: TeamProfile,
    *,
    observed_moving_times: Iterable[float] = (),
    observed_adjustment: float = 1.0,
) -> TimeEstimate:
    """Estimate one edge using the team profile stored with the network."""
    return estimate_edge_time(
        edge,
        base_speed_kmh=profile.base_speed_kmh,
        pack_multiplier=profile.pack_multiplier,
        team_multiplier=profile.team_multiplier,
        observed_moving_times=observed_moving_times,
        observed_adjustment=observed_adjustment,
    )


def observed_times_for_edge(network: RouteNetwork, edge_id: str) -> list[float]:
    """Collect comparable segment observations; whole-route times are excluded."""
    return [
        item.moving_time_hours
        for item in network.track_segment_observations
        if item.edge_id == edge_id
        and item.comparable
        and item.split_method != "whole-route"
        and item.moving_time_hours > 0
    ]


def calculate_cutoff_time(
    safe_arrival_deadline: str,
    remaining_p85_hours: float,
    fixed_buffer_minutes: int = 0,
    contingency_buffer_minutes: int = 0,
) -> str:
    """Back-calculate the latest time for leaving a decision point.

    Accepts ``HH:MM`` or an ISO date-time. A date-time input is recommended
    when a route can cross midnight.
    """
    if remaining_p85_hours < 0 or fixed_buffer_minutes < 0 or contingency_buffer_minutes < 0:
        raise ValueError("time and buffer inputs cannot be negative")

    has_date = "T" in safe_arrival_deadline or " " in safe_arrival_deadline.strip()
    if has_date:
        deadline = datetime.fromisoformat(safe_arrival_deadline)
    else:
        deadline = datetime.strptime(safe_arrival_deadline, "%H:%M").replace(
            year=2000, month=1, day=2
        )
    cutoff = deadline - timedelta(
        hours=remaining_p85_hours,
        minutes=fixed_buffer_minutes + contingency_buffer_minutes,
    )
    return cutoff.isoformat(timespec="minutes") if has_date else cutoff.strftime("%H:%M")


def validate_route_network(
    network: RouteNetwork,
    *,
    operational: bool = False,
) -> list[str]:
    """Return structural and evidence errors for a route network."""
    errors: list[str] = []
    evidence_by_id = {evidence.evidence_id: evidence for evidence in network.evidence}
    evidence_ids = set(evidence_by_id)

    def validate_state(owner: str, state) -> None:
        if state.verification_status not in VERIFICATION_RANK:
            errors.append(f"{owner}: invalid verification status {state.verification_status!r}")
        if state.availability_status not in AVAILABILITY_STATUSES:
            errors.append(f"{owner}: invalid availability status {state.availability_status!r}")
        if state.verification_status == "Desk Verified" and len(state.evidence_refs) < 2:
            errors.append(f"{owner}: Desk Verified requires at least two evidence references")
        if state.verification_status == "Field Verified":
            if not state.verified_at or not state.verified_by:
                errors.append(f"{owner}: Field Verified requires verified_at and verified_by")
            if not state.evidence_refs:
                errors.append(f"{owner}: Field Verified requires field evidence")
            elif not any(
                evidence_by_id.get(ref)
                and evidence_by_id[ref].source_type == "field"
                for ref in state.evidence_refs
            ):
                errors.append(f"{owner}: Field Verified requires evidence with source_type 'field'")
        for evidence_ref in state.evidence_refs:
            if evidence_ref not in evidence_ids:
                errors.append(f"{owner}: unknown evidence {evidence_ref}")

    validate_state("network", network.state)
    node_ids = [node.node_id for node in network.nodes]
    edge_ids = [edge.edge_id for edge in network.edges]
    if len(set(node_ids)) != len(node_ids):
        errors.append("node_id values must be unique")
    if len(set(edge_ids)) != len(edge_ids):
        errors.append("edge_id values must be unique")

    for node in network.nodes:
        validate_state(f"node {node.node_id}", node.state)
        if not node.node_id:
            errors.append("every node requires node_id")
    edge_by_id = {edge.edge_id: edge for edge in network.edges}
    track_ids = {track.track_id for track in network.track_sources}
    node_id_set = set(node_ids)
    for edge in network.edges:
        validate_state(f"edge {edge.edge_id}", edge.state)
        if edge.from_node not in node_id_set or edge.to_node not in node_id_set:
            errors.append(f"edge {edge.edge_id}: from_node/to_node must reference existing nodes")
        if edge.distance_km < 0 or edge.elevation_gain_m < 0 or edge.elevation_loss_m < 0:
            errors.append(f"edge {edge.edge_id}: distance and elevation values cannot be negative")
        for track_id in edge.track_source_ids:
            if track_id not in track_ids:
                errors.append(f"edge {edge.edge_id}: unknown track source {track_id}")

    for access in network.vehicle_access_points:
        validate_state(f"vehicle access {access.access_id}", access.state)
        if access.node_id not in node_id_set:
            errors.append(f"vehicle access {access.access_id}: unknown node {access.node_id}")

    for image in network.image_evidence:
        if image.node_id not in node_id_set:
            errors.append(f"image {image.image_id}: unknown node {image.node_id}")
        if image.evidence_ref and image.evidence_ref not in evidence_ids:
            errors.append(f"image {image.image_id}: unknown evidence {image.evidence_ref}")

    decision_by_id = {item.decision_id: item for item in network.decision_points}
    for decision in network.decision_points:
        validate_state(f"decision {decision.decision_id}", decision.state)
        if decision.node_id not in node_id_set:
            errors.append(f"decision {decision.decision_id}: unknown node {decision.node_id}")
        for edge_id in decision.main_edge_ids + decision.bailout_edge_ids:
            if edge_id not in edge_by_id:
                errors.append(f"decision {decision.decision_id}: unknown edge {edge_id}")
        if operational:
            if not decision.main_edge_ids:
                errors.append(f"decision {decision.decision_id}: operational use requires a main continuation")
            if not decision.bailout_edge_ids:
                errors.append(f"decision {decision.decision_id}: operational use requires a bailout")
            for edge_id in decision.bailout_edge_ids:
                edge = edge_by_id.get(edge_id)
                if edge and VERIFICATION_RANK.get(edge.state.verification_status, -1) < 1:
                    errors.append(
                        f"decision {decision.decision_id}: bailout edge {edge_id} must be Desk Verified or Field Verified"
                    )

    for cutoff in network.cutoff_points:
        validate_state(f"cutoff {cutoff.cutoff_id}", cutoff.state)
        if cutoff.decision_point_id not in decision_by_id:
            errors.append(
                f"cutoff {cutoff.cutoff_id}: unknown decision point {cutoff.decision_point_id}"
            )
        if not cutoff.safe_arrival_deadline or not cutoff.cutoff_time:
            errors.append(f"cutoff {cutoff.cutoff_id}: deadline and calculated cutoff are required")
        elif cutoff.safe_arrival_deadline and cutoff.cutoff_time:
            try:
                expected = calculate_cutoff_time(
                    cutoff.safe_arrival_deadline,
                    cutoff.remaining_p85_hours,
                    cutoff.fixed_buffer_minutes,
                    cutoff.contingency_buffer_minutes,
                )
                if cutoff.cutoff_time != expected:
                    errors.append(
                        f"cutoff {cutoff.cutoff_id}: cutoff_time should be {expected} for the stored inputs"
                    )
            except ValueError as exc:
                errors.append(f"cutoff {cutoff.cutoff_id}: invalid calculation input ({exc})")

    return errors


def main() -> int:
    """Validate a route-network JSON file from the command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate trail route-network JSON")
    parser.add_argument("input_json")
    parser.add_argument(
        "--operational",
        action="store_true",
        help="require each decision point to have a Desk/Field Verified bailout",
    )
    args = parser.parse_args()
    data = TrailResearchData.from_json(args.input_json)
    errors = validate_route_network(data.route_network, operational=args.operational)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Route network validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
