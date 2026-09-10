"""Export an operationally readable route-network GPX from TrailResearchData.

The GPX shows the planned main route, every candidate bailout route, decision
and cutoff information, segment conditions, evidence links, and optional
geotagged image links. It does not infer geometry or draw straight shortcuts.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

from data_model import (
    CutoffPoint,
    DecisionPoint,
    GeoPoint,
    ImageEvidence,
    RouteEdge,
    RouteNetwork,
    RouteNode,
    TrackSource,
    TrailResearchData,
)


GPX_NS = "http://www.topografix.com/GPX/1/1"
TR_NS = "https://notconverged.github.io/trail-research/route-network/1"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("", GPX_NS)
ET.register_namespace("tr", TR_NS)
ET.register_namespace("xsi", XSI_NS)


def _sub(parent: ET.Element, tag: str, text: object = "", attrs: dict[str, str] | None = None) -> ET.Element:
    element = ET.SubElement(parent, tag, attrs or {})
    if text not in (None, ""):
        element.text = str(text)
    return element


def _ext(parent: ET.Element, name: str, value: object) -> None:
    if value not in (None, "", [], {}):
        _sub(parent, f"{{{TR_NS}}}{name}", value)


def _parse_coordinate(node: RouteNode) -> tuple[float, float] | None:
    values = re.findall(r"[-+]?\d+(?:\.\d+)?", node.coordinate.gps)
    if len(values) < 2:
        return None
    lat, lon = float(values[0]), float(values[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _platform_priority(source: TrackSource) -> int:
    if source.source_priority > 0:
        return source.source_priority
    platform = source.platform.casefold()
    if "两步路" in platform or "2bulu" in platform:
        return 10
    if "六只脚" in platform or "foooooot" in platform:
        return 20
    if "wikiloc" in platform or "alltrails" in platform:
        return 30
    return 40


def _date_number(source: TrackSource) -> int:
    value = source.recorded_at or source.uploaded_at
    digits = re.sub(r"\D", "", value)[:14]
    return int(digits.ljust(14, "0")) if digits else 0


def ordered_sources(sources: Iterable[TrackSource]) -> list[TrackSource]:
    """Two Steps tracks first; within a tier, newer recorded/uploaded dates first."""
    return sorted(sources, key=lambda item: (_platform_priority(item), -_date_number(item), item.track_id))


def validate_export(network: RouteNetwork) -> list[str]:
    errors: list[str] = []
    node_ids = {node.node_id for node in network.nodes}
    source_ids = {source.track_id for source in network.track_sources}
    decision_nodes = {item.node_id for item in network.decision_points}

    if not any(edge.route_role == "main" for edge in network.edges):
        errors.append("route network has no main edge")
    if not any(edge.route_role == "bailout" for edge in network.edges):
        errors.append("route network has no bailout edge")
    for edge in network.edges:
        if edge.route_role not in {"main", "bailout", "alternate", "access"}:
            errors.append(f"{edge.edge_id}: unsupported route_role {edge.route_role}")
        if edge.from_node not in node_ids or edge.to_node not in node_ids:
            errors.append(f"{edge.edge_id}: from/to node is missing")
        if edge.route_role in {"main", "bailout"} and len(edge.geometry_points) < 2:
            errors.append(f"{edge.edge_id}: main/bailout edge needs at least 2 geometry_points")
        unknown_sources = set(edge.track_source_ids) - source_ids
        if unknown_sources:
            errors.append(f"{edge.edge_id}: unknown track sources {sorted(unknown_sources)}")
        if edge.route_role == "bailout" and not edge.gpx_route_id.startswith("BAILOUT-"):
            errors.append(f"{edge.edge_id}: bailout gpx_route_id must start with BAILOUT-")
    for decision in network.decision_points:
        if decision.node_id not in node_ids:
            errors.append(f"{decision.decision_id}: node is missing")
        if not decision.bailout_edge_ids:
            errors.append(f"{decision.decision_id}: no bailout edge")
        if not decision.planned_arrival_window:
            errors.append(f"{decision.decision_id}: planned_arrival_window is required for GPX")
    bailout_origins = {edge.from_node for edge in network.edges if edge.route_role == "bailout"}
    missing_decisions = bailout_origins - decision_nodes
    if missing_decisions:
        errors.append(f"bailout origins lack DecisionPoint: {sorted(missing_decisions)}")
    return errors


def _source_text(ids: list[str], source_map: dict[str, TrackSource]) -> str:
    sources = ordered_sources(source_map[item] for item in ids if item in source_map)
    parts = []
    for index, source in enumerate(sources, 1):
        date = source.recorded_at or source.uploaded_at or "日期未知"
        parts.append(f"S{index} {source.platform}/{source.track_id} ({date}) {source.url}".strip())
    return "；".join(parts)


def _edge_description(edge: RouteEdge, source_map: dict[str, TrackSource]) -> str:
    time = edge.time_estimate
    planned = ""
    if time.planned_lower_hours or time.planned_upper_hours:
        planned = f"计划时间 {time.planned_lower_hours:.2f}–{time.planned_upper_hours:.2f} h；"
    return (
        f"{edge.edge_id}；{edge.distance_km:.2f} km；+{edge.elevation_gain_m}/-{edge.elevation_loss_m} m；"
        f"{planned}路况：{edge.condition_summary or edge.difficulty.notes or '待核实'}；"
        f"验证：{edge.state.verification_status}/{edge.state.availability_status}；"
        f"来源：{_source_text(edge.track_source_ids, source_map) or '待补'}"
    )


def _route_label(route_id: str, edges: list[RouteEdge]) -> str:
    if route_id == "MAIN":
        return "[主线] " + " / ".join(edge.name or edge.edge_id for edge in edges)
    return "[下撤] " + " / ".join(edge.name or edge.edge_id for edge in edges)


def _waypoint_kind(
    node_id: str,
    decisions: dict[str, DecisionPoint],
    cutoff_by_decision: dict[str, CutoffPoint],
    bailout_origins: set[str],
    bailout_exits: set[str],
    vehicle_nodes: set[str],
) -> tuple[str, str]:
    if node_id in decisions:
        decision = decisions[node_id]
        cutoff = cutoff_by_decision.get(decision.decision_id)
        suffix = f" / CP {cutoff.cutoff_time}" if cutoff and cutoff.cutoff_time else ""
        return "DECISION", f"[DP {decision.decision_id}{suffix}]"
    if node_id in bailout_origins:
        return "BAILOUT_START", "[下撤点]"
    if node_id in bailout_exits:
        return "BAILOUT_EXIT", "[下撤出口]"
    if node_id in vehicle_nodes:
        return "VEHICLE", "[车辆点]"
    return "KEY_POINT", "[关键点]"


def _add_link(parent: ET.Element, href: str, text: str, mime_type: str = "") -> None:
    link = ET.SubElement(parent, f"{{{GPX_NS}}}link", {"href": href})
    _sub(link, f"{{{GPX_NS}}}text", text)
    if mime_type:
        _sub(link, f"{{{GPX_NS}}}type", mime_type)


def export_route_network_gpx(data: TrailResearchData, output_path: Path) -> dict[str, object]:
    network = data.route_network
    errors = validate_export(network)
    if errors:
        raise ValueError("GPX export validation failed:\n- " + "\n- ".join(errors))

    source_map = {source.track_id: source for source in network.track_sources}
    ordered = ordered_sources(network.track_sources)
    node_map = {node.node_id: node for node in network.nodes}
    decisions = {item.node_id: item for item in network.decision_points}
    cutoff_by_decision = {item.decision_point_id: item for item in network.cutoff_points}
    bailout_edges = [edge for edge in network.edges if edge.route_role == "bailout"]
    bailout_origins = {edge.from_node for edge in bailout_edges}
    bailout_exits = {edge.to_node for edge in bailout_edges}
    vehicle_nodes = {item.node_id for item in network.vehicle_access_points}
    images_by_node: dict[str, list[ImageEvidence]] = defaultdict(list)
    for image in network.image_evidence:
        images_by_node[image.node_id].append(image)

    root = ET.Element(f"{{{GPX_NS}}}gpx", {
        "version": "1.1",
        "creator": "trail-research route_network_gpx.py",
        f"{{{XSI_NS}}}schemaLocation": f"{GPX_NS} http://www.topografix.com/GPX/1/1/gpx.xsd",
    })
    metadata = ET.SubElement(root, f"{{{GPX_NS}}}metadata")
    _sub(metadata, f"{{{GPX_NS}}}name", network.name or data.route.name)
    _sub(metadata, f"{{{GPX_NS}}}desc", "Phase 4 路网：主线、候选下撤、决策/截止点、区间路况与来源。状态以配套 Markdown 为准。")
    _sub(metadata, f"{{{GPX_NS}}}time", datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    metadata_ext = ET.SubElement(metadata, f"{{{GPX_NS}}}extensions")
    _ext(metadata_ext, "verification_status", network.state.verification_status)
    _ext(metadata_ext, "availability_status", network.state.availability_status)
    for index, source in enumerate(ordered, 1):
        element = ET.SubElement(metadata_ext, f"{{{TR_NS}}}source", {
            "order": str(index), "priority": str(_platform_priority(source)), "track_id": source.track_id,
        })
        element.text = f"{source.platform}|{source.recorded_at or source.uploaded_at}|{source.url}"

    key_node_ids = set(decisions) | bailout_origins | bailout_exits | vehicle_nodes
    key_node_ids |= {node.node_id for node in network.nodes if node.node_types}
    waypoint_count = 0
    image_link_count = 0
    for node in network.nodes:
        if node.node_id not in key_node_ids:
            continue
        coordinate = _parse_coordinate(node)
        if coordinate is None:
            raise ValueError(f"{node.node_id}: key GPX node has no valid WGS84 coordinate")
        kind, prefix = _waypoint_kind(
            node.node_id, decisions, cutoff_by_decision,
            bailout_origins, bailout_exits, vehicle_nodes,
        )
        waypoint = ET.SubElement(root, f"{{{GPX_NS}}}wpt", {"lat": f"{coordinate[0]:.7f}", "lon": f"{coordinate[1]:.7f}"})
        _sub(waypoint, f"{{{GPX_NS}}}name", f"{prefix} {node.name} ({node.node_id})")
        decision = decisions.get(node.node_id)
        cutoff = cutoff_by_decision.get(decision.decision_id) if decision else None
        connected = [edge for edge in network.edges if edge.from_node == node.node_id or edge.to_node == node.node_id]
        descriptions = [f"类型：{kind}", f"识别：{node.field_identification or '待核实'}", f"信号：{node.signal_summary or '待核实'}"]
        if decision:
            descriptions.extend([
                f"计划到达：{decision.planned_arrival_window}",
                f"继续主线：{','.join(decision.main_edge_ids)}",
                f"下撤：{','.join(decision.bailout_edge_ids)}",
                f"触发：{'；'.join(decision.trigger_conditions)}",
                f"动作：{decision.decision_action}",
            ])
        if cutoff:
            descriptions.extend([
                f"截止：{cutoff.cutoff_time or '待计算'}",
                f"安全到达时限：{cutoff.safe_arrival_deadline or '待确认'}",
                f"剩余P85：{cutoff.remaining_p85_hours:.2f} h",
                f"截止后动作：{cutoff.action_after_cutoff}",
            ])
        if connected:
            descriptions.append("相邻路段：" + " | ".join(_edge_description(edge, source_map) for edge in connected))
        _sub(waypoint, f"{{{GPX_NS}}}desc", "；".join(descriptions))
        for image in images_by_node.get(node.node_id, []):
            href = image.direct_image_url or image.source_url
            if not href:
                continue
            label = f"{image.source_platform or '来源'}路标图片/原帖 {image.image_id}"
            _add_link(waypoint, href, label, "image/jpeg" if image.direct_image_url else "text/html")
            image_link_count += 1
        extensions = ET.SubElement(waypoint, f"{{{GPX_NS}}}extensions")
        _ext(extensions, "node_id", node.node_id)
        _ext(extensions, "point_role", kind)
        _ext(extensions, "planned_arrival_window", decision.planned_arrival_window if decision else node.planned_arrival_window)
        _ext(extensions, "cutoff_time", cutoff.cutoff_time if cutoff else "")
        _ext(extensions, "verification_status", node.state.verification_status)
        _ext(extensions, "availability_status", node.state.availability_status)
        waypoint_count += 1

    grouped_edges: dict[str, list[RouteEdge]] = defaultdict(list)
    for edge in network.edges:
        if edge.route_role in {"main", "bailout"}:
            grouped_edges[edge.gpx_route_id].append(edge)
    route_ids = sorted(grouped_edges, key=lambda item: (item != "MAIN", item))
    trackpoint_count = 0
    for route_id in route_ids:
        edges = grouped_edges[route_id]
        track = ET.SubElement(root, f"{{{GPX_NS}}}trk")
        _sub(track, f"{{{GPX_NS}}}name", _route_label(route_id, edges))
        _sub(track, f"{{{GPX_NS}}}desc", " | ".join(_edge_description(edge, source_map) for edge in edges))
        track_ext = ET.SubElement(track, f"{{{GPX_NS}}}extensions")
        _ext(track_ext, "route_id", route_id)
        _ext(track_ext, "route_role", "main" if route_id == "MAIN" else "bailout")
        for edge in edges:
            segment = ET.SubElement(track, f"{{{GPX_NS}}}trkseg")
            for point in edge.geometry_points:
                trackpoint = ET.SubElement(segment, f"{{{GPX_NS}}}trkpt", {"lat": f"{point.lat:.7f}", "lon": f"{point.lon:.7f}"})
                if point.elevation_m:
                    _sub(trackpoint, f"{{{GPX_NS}}}ele", f"{point.elevation_m:.1f}")
                if point.time:
                    _sub(trackpoint, f"{{{GPX_NS}}}time", point.time)
                trackpoint_count += 1
            segment_ext = ET.SubElement(segment, f"{{{GPX_NS}}}extensions")
            _ext(segment_ext, "edge_id", edge.edge_id)
            _ext(segment_ext, "condition_summary", edge.condition_summary or edge.difficulty.notes)
            _ext(segment_ext, "distance_km", edge.distance_km)
            _ext(segment_ext, "elevation_gain_m", edge.elevation_gain_m)
            _ext(segment_ext, "elevation_loss_m", edge.elevation_loss_m)
            _ext(segment_ext, "planned_time_hours", f"{edge.time_estimate.planned_lower_hours:.2f}-{edge.time_estimate.planned_upper_hours:.2f}")
            _ext(segment_ext, "source_order", _source_text(edge.track_source_ids, source_map))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
    return {
        "track_count": len(route_ids),
        "main_track_count": int("MAIN" in grouped_edges),
        "bailout_track_count": sum(route_id != "MAIN" for route_id in route_ids),
        "trackpoint_count": trackpoint_count,
        "waypoint_count": waypoint_count,
        "image_link_count": image_link_count,
        "source_order": [source.track_id for source in ordered],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_gpx", type=Path)
    args = parser.parse_args()
    data = TrailResearchData.from_json(str(args.input_json))
    result = export_route_network_gpx(data, args.output_gpx)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
