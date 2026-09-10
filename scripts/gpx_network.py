"""Build an auditable multi-source GPX overlay for route-network research.

The output preserves source tracks as separate GPX tracks. It is a research
overlay, not a consensus line and not a navigation-ready route.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


GPX_NS = "http://www.topografix.com/GPX/1/1"
TR_NS = "https://notconverged.github.io/trail-research/1"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("", GPX_NS)
ET.register_namespace("tr", TR_NS)
ET.register_namespace("xsi", XSI_NS)


@dataclass
class Point:
    lat: float
    lon: float
    ele: float | None = None
    time: str | None = None


@dataclass
class Waypoint(Point):
    name: str = ""
    description: str = ""
    original_id: str = ""


@dataclass
class ParsedSource:
    source: dict[str, Any]
    path: Path | None
    sha256: str = ""
    segments: list[list[Point]] = field(default_factory=list)
    waypoints: list[Waypoint] = field(default_factory=list)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _read_xml(path: Path) -> ET.Element:
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
            if not names:
                raise ValueError(f"KMZ contains no KML: {path}")
            return ET.fromstring(archive.read(names[0]))
    return ET.parse(path).getroot()


def parse_gpx(path: Path, source: dict[str, Any]) -> ParsedSource:
    root = _read_xml(path)
    parsed = ParsedSource(source=source, path=path)
    for element in root.iter():
        kind = _local_name(element.tag)
        if kind == "wpt":
            parsed.waypoints.append(
                Waypoint(
                    lat=float(element.attrib["lat"]),
                    lon=float(element.attrib["lon"]),
                    ele=_float_or_none(_child_text(element, "ele")),
                    time=_child_text(element, "time") or None,
                    name=_child_text(element, "name"),
                    description=_child_text(element, "desc"),
                )
            )
        elif kind == "trkseg":
            segment = []
            for point in element:
                if _local_name(point.tag) != "trkpt":
                    continue
                segment.append(
                    Point(
                        lat=float(point.attrib["lat"]),
                        lon=float(point.attrib["lon"]),
                        ele=_float_or_none(_child_text(point, "ele")),
                        time=_child_text(point, "time") or None,
                    )
                )
            if segment:
                parsed.segments.append(segment)
        elif kind == "rte":
            segment = []
            for point in element:
                if _local_name(point.tag) != "rtept":
                    continue
                segment.append(
                    Point(
                        lat=float(point.attrib["lat"]),
                        lon=float(point.attrib["lon"]),
                        ele=_float_or_none(_child_text(point, "ele")),
                        time=_child_text(point, "time") or None,
                    )
                )
            if segment:
                parsed.segments.append(segment)
    return parsed


def _parse_coordinates(text: str) -> list[Point]:
    points = []
    for item in text.replace("\n", " ").split():
        parts = item.split(",")
        if len(parts) < 2:
            continue
        points.append(Point(lat=float(parts[1]), lon=float(parts[0]), ele=_float_or_none(parts[2] if len(parts) > 2 else None)))
    return points


def parse_kml(path: Path, source: dict[str, Any]) -> ParsedSource:
    root = _read_xml(path)
    parsed = ParsedSource(source=source, path=path)
    for placemark in (item for item in root.iter() if _local_name(item.tag) == "Placemark"):
        name = _child_text(placemark, "name")
        description = _child_text(placemark, "description")
        for element in placemark.iter():
            kind = _local_name(element.tag)
            if kind == "Point":
                coord = next((x.text for x in element.iter() if _local_name(x.tag) == "coordinates" and x.text), "")
                points = _parse_coordinates(coord)
                if points:
                    point = points[0]
                    parsed.waypoints.append(Waypoint(**point.__dict__, name=name, description=description))
            elif kind == "LineString":
                coord = next((x.text for x in element.iter() if _local_name(x.tag) == "coordinates" and x.text), "")
                segment = _parse_coordinates(coord)
                if segment:
                    parsed.segments.append(segment)
            elif kind == "Track":
                times = [x.text.strip() for x in element if _local_name(x.tag) == "when" and x.text]
                coords = [x.text.strip().split() for x in element if _local_name(x.tag) == "coord" and x.text]
                segment = []
                for index, parts in enumerate(coords):
                    if len(parts) >= 2:
                        segment.append(Point(
                            lat=float(parts[1]), lon=float(parts[0]),
                            ele=_float_or_none(parts[2] if len(parts) > 2 else None),
                            time=times[index] if index < len(times) else None,
                        ))
                if segment:
                    parsed.segments.append(segment)
    return parsed


def _decode_varints(payload: str) -> list[int]:
    values, value, shift = [], 0, 0
    for byte in base64.b64decode(payload):
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
        else:
            values.append((value >> 1) ^ -(value & 1))
            value, shift = 0, 0
    if shift:
        raise ValueError("truncated varint payload")
    return values


def parse_rendered_page_geometry(path: Path, source: dict[str, Any]) -> ParsedSource:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("preview_encoding") != "delta-zigzag-varint-base64":
        raise ValueError(f"unsupported rendered-page encoding: {path}")
    dimensions = data["preview_dimensions"]
    values = _decode_varints(data["preview_payload"])
    width = len(dimensions)
    if not width or len(values) % width:
        raise ValueError(f"invalid point payload dimensions: {path}")
    running = [0] * width
    points = []
    for offset in range(0, len(values), width):
        running = [a + b for a, b in zip(running, values[offset:offset + width])]
        row = dict(zip(dimensions, running))
        timestamp = row.get("time_s")
        points.append(Point(
            lat=row["lat_e6"] / 1_000_000,
            lon=row["lon_e6"] / 1_000_000,
            ele=row.get("ele_dm", 0) / 10 if "ele_dm" in row else None,
            time=datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z") if timestamp else None,
        ))
    parsed = ParsedSource(source={**data, **source}, path=path, segments=[points])
    for item in data.get("waypoints", []):
        parsed.waypoints.append(Waypoint(
            lat=float(item["lat"]), lon=float(item["lon"]),
            ele=_float_or_none(str(item.get("elevation", ""))),
            name=str(item.get("name", "")), original_id=str(item.get("id", "")),
        ))
    return parsed


def parse_source(source: dict[str, Any], manifest_dir: Path) -> ParsedSource:
    tier = source.get("source_tier", "")
    if tier == "metadata_only":
        return ParsedSource(source=source, path=None)
    coordinate_system = source.get("coordinate_system", "unknown")
    if coordinate_system != "WGS84":
        raise ValueError(f"{source.get('source_id')}: coordinate_system must be WGS84, got {coordinate_system}")
    path = (manifest_dir / source["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    source_format = source.get("source_format", path.suffix.lstrip(".")).lower().replace("_", "-")
    if source_format == "gpx":
        parsed = parse_gpx(path, source)
    elif source_format in {"kml", "kmz"}:
        parsed = parse_kml(path, source)
    elif source_format in {"rendered-page-geometry", "rendered-page-json"}:
        parsed = parse_rendered_page_geometry(path, source)
    else:
        raise ValueError(f"{source.get('source_id')}: unsupported source_format {source_format}")
    parsed.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return parsed


def haversine_m(a: Point, b: Point) -> float:
    radius = 6_371_008.8
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def _metrics(segments: list[list[Point]]) -> dict[str, Any]:
    distance, gain, loss, jumps = 0.0, 0.0, 0.0, []
    points = [point for segment in segments for point in segment]
    for segment_index, segment in enumerate(segments):
        for point_index, (a, b) in enumerate(zip(segment, segment[1:]), start=1):
            step = haversine_m(a, b)
            distance += step
            if step > 2_000:
                jumps.append({"segment": segment_index + 1, "point": point_index + 1, "distance_m": round(step, 1)})
            if a.ele is not None and b.ele is not None:
                delta = b.ele - a.ele
                gain += max(delta, 0)
                loss += max(-delta, 0)
    return {
        "track_count": 1 if segments else 0,
        "segment_count": len(segments),
        "point_count": len(points),
        "distance_km": round(distance / 1000, 3),
        "elevation_gain_m_unfiltered": round(gain, 1),
        "elevation_loss_m_unfiltered": round(loss, 1),
        "missing_elevation_points": sum(point.ele is None for point in points),
        "missing_time_points": sum(point.time is None for point in points),
        "jumps_over_2km": jumps,
        "bbox": ({
            "min_lat": min(point.lat for point in points), "max_lat": max(point.lat for point in points),
            "min_lon": min(point.lon for point in points), "max_lon": max(point.lon for point in points),
        } if points else None),
    }


def _duplicate_groups(items: list[tuple[str, Waypoint]], threshold_m: float) -> dict[int, str]:
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][0] != items[j][0] and haversine_m(items[i][1], items[j][1]) <= threshold_m:
                union(i, j)
    roots: dict[int, list[int]] = {}
    for i in range(len(items)):
        roots.setdefault(find(i), []).append(i)
    groups, counter = {}, 0
    for members in roots.values():
        if len(members) > 1:
            counter += 1
            for member in members:
                groups[member] = f"DG-{counter:03d}"
    return groups


def _sub(parent: ET.Element, name: str, text: Any) -> ET.Element:
    child = ET.SubElement(parent, name)
    child.text = str(text)
    return child


def _extension(parent: ET.Element, name: str, value: Any) -> None:
    if value not in (None, ""):
        _sub(parent, f"{{{TR_NS}}}{name}", value)


def build_overlay(manifest_path: Path, output_path: Path, qc_path: Path | None = None) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parsed_sources = [parse_source(source, manifest_path.parent) for source in manifest.get("sources", [])]

    supplemental = []
    for item in manifest.get("supplemental_waypoints", []):
        if item.get("coordinate_system", "WGS84") != "WGS84":
            raise ValueError(f"supplemental waypoint {item.get('name')}: coordinate_system must be WGS84")
        supplemental.append((item.get("source_id", "SUPPLEMENTAL"), Waypoint(
            lat=float(item["lat"]), lon=float(item["lon"]), ele=_float_or_none(str(item.get("ele", ""))),
            name=item.get("name", ""), description=item.get("description", ""), original_id=item.get("id", ""),
        ), item))

    waypoint_items: list[tuple[str, Waypoint, dict[str, Any]]] = []
    for parsed in parsed_sources:
        for waypoint in parsed.waypoints:
            waypoint_items.append((
                parsed.source.get("source_id", "UNKNOWN"), waypoint,
                {**parsed.source, "source_sha256": parsed.sha256},
            ))
    waypoint_items.extend(supplemental)
    duplicate_threshold = float(manifest.get("waypoint_duplicate_threshold_m", 100))
    duplicate_groups = _duplicate_groups([(source_id, waypoint) for source_id, waypoint, _ in waypoint_items], duplicate_threshold)

    root = ET.Element(f"{{{GPX_NS}}}gpx", {
        "version": "1.1", "creator": "trail-research gpx_network.py",
        f"{{{XSI_NS}}}schemaLocation": f"{GPX_NS} http://www.topografix.com/GPX/1/1/gpx.xsd",
    })
    metadata = ET.SubElement(root, f"{{{GPX_NS}}}metadata")
    _sub(metadata, f"{{{GPX_NS}}}name", manifest.get("name", "Route network research overlay"))
    _sub(metadata, f"{{{GPX_NS}}}desc", "多来源路网研究叠加层；各来源轨迹保持独立，未拼接为共识路线，不可直接用于导航。")
    _sub(metadata, f"{{{GPX_NS}}}time", datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))

    for index, (source_id, waypoint, source) in enumerate(waypoint_items):
        element = ET.SubElement(root, f"{{{GPX_NS}}}wpt", {"lat": f"{waypoint.lat:.7f}", "lon": f"{waypoint.lon:.7f}"})
        if waypoint.ele is not None:
            _sub(element, f"{{{GPX_NS}}}ele", f"{waypoint.ele:.1f}")
        if waypoint.time:
            _sub(element, f"{{{GPX_NS}}}time", waypoint.time)
        _sub(element, f"{{{GPX_NS}}}name", f"[{source_id}] {waypoint.name or waypoint.original_id or '未命名标注'}")
        if waypoint.description:
            _sub(element, f"{{{GPX_NS}}}desc", waypoint.description)
        extensions = ET.SubElement(element, f"{{{GPX_NS}}}extensions")
        _extension(extensions, "source_id", source_id)
        _extension(extensions, "original_id", waypoint.original_id)
        _extension(extensions, "original_name", waypoint.name)
        _extension(extensions, "source_url", source.get("url"))
        _extension(extensions, "source_sha256", source.get("source_sha256"))
        _extension(extensions, "verification_status", source.get("verification_status", "Candidate"))
        _extension(extensions, "coordinate_system", source.get("coordinate_system", "WGS84"))
        _extension(extensions, "geometry_provenance", source.get("geometry_provenance") or source.get("source_geometry_format"))
        _extension(extensions, "dedupe_group", duplicate_groups.get(index))

    qc_sources = []
    for parsed in parsed_sources:
        source = parsed.source
        metrics = _metrics(parsed.segments)
        reported = source.get("reported_distance_km") or source.get("distance_km")
        qc_sources.append({
            "source_id": source.get("source_id"), "source_tier": source.get("source_tier"),
            "source_format": source.get("source_format"), "path": str(parsed.path) if parsed.path else None,
            "sha256": parsed.sha256 or None, "verification_status": source.get("verification_status", "Candidate"),
            "waypoint_count": len(parsed.waypoints), **metrics,
            "reported_distance_km": reported,
            "distance_delta_percent": round((metrics["distance_km"] - float(reported)) / float(reported) * 100, 1) if reported and metrics["point_count"] else None,
        })
        if not parsed.segments:
            continue
        track = ET.SubElement(root, f"{{{GPX_NS}}}trk")
        _sub(track, f"{{{GPX_NS}}}name", f"[{source.get('source_id')}] {source.get('title') or source.get('name') or '来源轨迹'}")
        _sub(track, f"{{{GPX_NS}}}desc", source.get("notes", ""))
        extensions = ET.SubElement(track, f"{{{GPX_NS}}}extensions")
        for key, value in (
            ("source_id", source.get("source_id")), ("source_url", source.get("url")),
            ("source_sha256", parsed.sha256), ("source_tier", source.get("source_tier")),
            ("source_format", source.get("source_format")),
            ("geometry_provenance", source.get("geometry_provenance") or source.get("source_geometry_format")),
            ("verification_status", source.get("verification_status", "Candidate")),
            ("coordinate_system", source.get("coordinate_system", "WGS84")),
            ("acquisition_method", source.get("acquisition_method")),
        ):
            _extension(extensions, key, value)
        for segment in parsed.segments:
            segment_element = ET.SubElement(track, f"{{{GPX_NS}}}trkseg")
            for point in segment:
                point_element = ET.SubElement(segment_element, f"{{{GPX_NS}}}trkpt", {"lat": f"{point.lat:.7f}", "lon": f"{point.lon:.7f}"})
                if point.ele is not None:
                    _sub(point_element, f"{{{GPX_NS}}}ele", f"{point.ele:.1f}")
                if point.time:
                    _sub(point_element, f"{{{GPX_NS}}}time", point.time)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
    qc = {
        "manifest": str(manifest_path.resolve()), "output_gpx": str(output_path.resolve()),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "coordinate_system": "WGS84", "navigation_ready": False,
        "source_count": len(parsed_sources), "geometry_source_count": sum(bool(item.segments) for item in parsed_sources),
        "track_count": sum(bool(item.segments) for item in parsed_sources),
        "segment_count": sum(len(item.segments) for item in parsed_sources),
        "trackpoint_count": sum(sum(len(segment) for segment in item.segments) for item in parsed_sources),
        "waypoint_count": len(waypoint_items), "waypoint_duplicate_threshold_m": duplicate_threshold,
        "duplicate_groups": sorted(set(duplicate_groups.values())), "sources": qc_sources,
    }
    if qc_path:
        qc_path.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    return qc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--qc", type=Path)
    args = parser.parse_args()
    qc = build_overlay(args.manifest, args.output, args.qc)
    print(json.dumps(qc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
