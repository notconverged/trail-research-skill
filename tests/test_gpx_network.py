import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gpx_network import GPX_NS, TR_NS, build_overlay  # noqa: E402


def encode_rows(rows):
    previous = [0] * len(rows[0])
    output = bytearray()
    for row in rows:
        for value, old in zip(row, previous):
            signed = value - old
            unsigned = (signed << 1) ^ (signed >> 63)
            while unsigned >= 0x80:
                output.append((unsigned & 0x7F) | 0x80)
                unsigned >>= 7
            output.append(unsigned)
        previous = row
    return base64.b64encode(output).decode()


class GpxNetworkTests(unittest.TestCase):
    def test_merge_keeps_tracks_separate_and_waypoints(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "a.gpx").write_text(
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
                '<wpt lat="40" lon="116"><name>A</name></wpt>'
                '<trk><trkseg><trkpt lat="40" lon="116"/><trkpt lat="40.01" lon="116.01"/></trkseg></trk>'
                '</gpx>', encoding="utf-8")
            (folder / "b.kml").write_text(
                '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>B</name>'
                '<Point><coordinates>116.0001,40.0001,10</coordinates></Point></Placemark>'
                '<Placemark><LineString><coordinates>116.1,40.1,10 116.2,40.2,20</coordinates>'
                '</LineString></Placemark></Document></kml>', encoding="utf-8")
            manifest = {
                "sources": [
                    {"source_id": "A", "path": "a.gpx", "source_format": "gpx", "source_tier": "original_export", "coordinate_system": "WGS84"},
                    {"source_id": "B", "path": "b.kml", "source_format": "kml", "source_tier": "original_export", "coordinate_system": "WGS84"},
                ]
            }
            manifest_path = folder / "manifest.json"
            output_path = folder / "overlay.gpx"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            qc = build_overlay(manifest_path, output_path)
            root = ET.parse(output_path).getroot()
            self.assertEqual(len(root.findall(f"{{{GPX_NS}}}trk")), 2)
            self.assertEqual(len(root.findall(f"{{{GPX_NS}}}wpt")), 2)
            self.assertEqual(qc["trackpoint_count"], 4)
            groups = root.findall(f".//{{{TR_NS}}}dedupe_group")
            self.assertEqual(len(groups), 2)
            hashes = root.findall(f".//{{{GPX_NS}}}wpt/{{{GPX_NS}}}extensions/{{{TR_NS}}}source_sha256")
            self.assertEqual(len(hashes), 2)
            self.assertTrue(all(len(item.text) == 64 for item in hashes))

    def test_rendered_page_payload_is_decoded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            page = {
                "preview_encoding": "delta-zigzag-varint-base64",
                "preview_dimensions": ["lon_e6", "lat_e6", "ele_dm", "time_s"],
                "preview_payload": encode_rows([[116000000, 40000000, 1000, 0], [116001000, 40001000, 1010, 1]]),
                "waypoints": [{"id": 1, "name": "点", "lat": 40, "lon": 116}],
            }
            (folder / "page.json").write_text(json.dumps(page), encoding="utf-8")
            manifest = {"sources": [{
                "source_id": "PAGE", "path": "page.json", "source_format": "rendered-page-geometry",
                "source_tier": "rendered_page_geometry", "coordinate_system": "WGS84", "verification_status": "Candidate",
            }]}
            manifest_path, output_path = folder / "manifest.json", folder / "overlay.gpx"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            qc = build_overlay(manifest_path, output_path)
            self.assertEqual(qc["trackpoint_count"], 2)
            first = ET.parse(output_path).getroot().find(f".//{{{GPX_NS}}}trkpt")
            self.assertEqual(first.attrib, {"lat": "40.0000000", "lon": "116.0000000"})

    def test_non_wgs84_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "a.gpx").write_text('<gpx version="1.1"/>', encoding="utf-8")
            manifest_path = folder / "manifest.json"
            manifest_path.write_text(json.dumps({"sources": [{
                "source_id": "A", "path": "a.gpx", "source_format": "gpx",
                "source_tier": "original_export", "coordinate_system": "GCJ-02",
            }]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be WGS84"):
                build_overlay(manifest_path, folder / "out.gpx")

    def test_metadata_only_source_is_reported_without_track(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest_path = folder / "manifest.json"
            manifest_path.write_text(json.dumps({"sources": [{
                "source_id": "META", "source_format": "metadata-only", "source_tier": "metadata_only"
            }]}), encoding="utf-8")
            qc = build_overlay(manifest_path, folder / "out.gpx")
            self.assertEqual(qc["source_count"], 1)
            self.assertEqual(qc["track_count"], 0)


if __name__ == "__main__":
    unittest.main()
