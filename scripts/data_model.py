"""Shared data model for trail research document generation."""

from dataclasses import dataclass, field
import warnings


@dataclass
class RouteSegment:
    name: str = ""
    distance_km: float = 0.0
    elevation_gain_m: int = 0
    elevation_loss_m: int = 0
    surface_types: list[str] = field(default_factory=list)
    special_hazards: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class MeetingPoint:
    name: str = ""
    time: str = ""
    location: str = ""


@dataclass
class ScheduleItem:
    time: str = ""
    activity: str = ""


@dataclass
class CoordinateInfo:
    gps: str = ""              # e.g. "40.123456, 116.123456"
    searchable_name: str = ""  # 高德/百度可直接搜索的地名
    map_keyword: str = ""      # 推荐的地图搜索关键词


@dataclass
class GeoPoint:
    lat: float = 0.0
    lon: float = 0.0
    elevation_m: float = 0.0
    time: str = ""


@dataclass
class EvidenceReference:
    evidence_id: str = ""
    title: str = ""
    source_type: str = ""       # official / gpx / rednote / field / other
    platform: str = ""
    url: str = ""
    published_at: str = ""
    retrieved_at: str = ""
    supports: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class VerificationState:
    verification_status: str = "Candidate"  # Candidate / Desk Verified / Field Verified
    availability_status: str = "Unknown"    # Open / Restricted / Closed / Unknown
    verified_at: str = ""
    verified_by: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)


@dataclass
class TrackSource:
    track_id: str = ""
    platform: str = ""
    url: str = ""
    uploaded_at: str = ""
    recorded_at: str = ""
    retrieved_at: str = ""
    direction: str = ""
    distance_km: float = 0.0
    elevation_gain_m: int = 0
    elevation_loss_m: int = 0
    moving_time_hours: float = 0.0
    elapsed_time_hours: float = 0.0
    gpx_available: bool = False
    gpx_checksum: str = ""
    source_priority: int = 0       # 0=按平台规则自动排序；较小值优先
    priority_basis: str = ""
    original_file_path: str = ""
    original_file_sha256: str = ""
    source_format: str = ""
    coordinate_system: str = ""
    waypoint_photo_count: int = 0
    applies_to_edge_ids: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class TrackSegmentObservation:
    observation_id: str = ""
    track_id: str = ""
    edge_id: str = ""
    moving_time_hours: float = 0.0
    split_method: str = ""       # timestamped-gpx / platform-segment / whole-route
    comparable: bool = True
    exclusion_reason: str = ""
    notes: str = ""


@dataclass
class EdgeDifficulty:
    trail_grade: int = 0
    terrain_types: list[str] = field(default_factory=list)
    route_finding: str = ""     # low / medium / high
    technical_descent_m: int = 0
    terrain_multiplier: float = 1.0
    notes: str = ""


@dataclass
class TimeEstimate:
    baseline_hours: float = 0.0
    model_lower_hours: float = 0.0
    model_upper_hours: float = 0.0
    observed_p50_hours: float = 0.0
    observed_p85_hours: float = 0.0
    planned_lower_hours: float = 0.0
    planned_upper_hours: float = 0.0
    base_speed_kmh: float = 2.5
    ascent_rate_m_per_hour: float = 450.0
    descent_rate_m_per_hour: float = 700.0
    pack_multiplier: float = 1.0
    team_multiplier: float = 1.0
    uncertainty_multiplier: float = 1.0
    methodology_version: str = "route-time-v1"
    notes: list[str] = field(default_factory=list)


@dataclass
class RouteNode:
    node_id: str = ""
    name: str = ""
    node_types: list[str] = field(default_factory=list)
    coordinate: CoordinateInfo = field(default_factory=CoordinateInfo)
    field_identification: str = ""
    planned_arrival_window: str = ""
    signal_summary: str = ""
    state: VerificationState = field(default_factory=VerificationState)
    image_refs: list[str] = field(default_factory=list)


@dataclass
class RouteEdge:
    edge_id: str = ""
    from_node: str = ""
    to_node: str = ""
    name: str = ""
    route_role: str = "main"    # main / bailout / alternate / access
    directionality: str = "both"
    gpx_route_id: str = "MAIN"  # MAIN 或 BAILOUT-xx；同一路线的边使用同一 ID
    distance_km: float = 0.0
    elevation_gain_m: int = 0
    elevation_loss_m: int = 0
    condition_summary: str = ""
    geometry_points: list[GeoPoint] = field(default_factory=list)
    difficulty: EdgeDifficulty = field(default_factory=EdgeDifficulty)
    time_estimate: TimeEstimate = field(default_factory=TimeEstimate)
    state: VerificationState = field(default_factory=VerificationState)
    track_source_ids: list[str] = field(default_factory=list)


@dataclass
class VehicleAccessPoint:
    access_id: str = ""
    node_id: str = ""
    road_name: str = ""
    road_surface: str = ""
    road_width: str = ""
    vehicle_limit: str = ""
    turnaround: str = ""
    parking_capacity: str = ""
    navigation_keyword: str = ""
    last_vehicle_check_at: str = ""
    state: VerificationState = field(default_factory=VerificationState)


@dataclass
class DecisionPoint:
    decision_id: str = ""
    node_id: str = ""
    main_edge_ids: list[str] = field(default_factory=list)
    bailout_edge_ids: list[str] = field(default_factory=list)
    trigger_conditions: list[str] = field(default_factory=list)
    planned_arrival_window: str = ""
    decision_action: str = ""
    state: VerificationState = field(default_factory=VerificationState)
    notes: str = ""


@dataclass
class CutoffPoint:
    cutoff_id: str = ""
    decision_point_id: str = ""
    safe_arrival_deadline: str = ""
    cutoff_time: str = ""
    remaining_p85_hours: float = 0.0
    fixed_buffer_minutes: int = 0
    contingency_buffer_minutes: int = 0
    calculation_inputs: list[str] = field(default_factory=list)
    action_after_cutoff: str = ""
    state: VerificationState = field(default_factory=VerificationState)


@dataclass
class ImageEvidence:
    image_id: str = ""
    node_id: str = ""
    source_url: str = ""
    direct_image_url: str = ""
    track_source_id: str = ""
    source_platform: str = ""
    author: str = ""
    captured_at: str = ""
    retrieved_at: str = ""
    viewpoint: str = ""
    visible_feature: str = ""
    reuse_status: str = "link-only"  # link-only / permitted / own-field-photo
    evidence_ref: str = ""


@dataclass
class TeamProfile:
    name: str = "普通队伍"
    base_speed_kmh: float = 2.5
    pack_multiplier: float = 1.0
    team_multiplier: float = 1.0
    notes: str = ""


@dataclass
class RouteNetwork:
    schema_version: str = "1.0"
    network_id: str = ""
    name: str = ""
    state: VerificationState = field(default_factory=VerificationState)
    team_profile: TeamProfile = field(default_factory=TeamProfile)
    nodes: list[RouteNode] = field(default_factory=list)
    edges: list[RouteEdge] = field(default_factory=list)
    track_sources: list[TrackSource] = field(default_factory=list)
    track_segment_observations: list[TrackSegmentObservation] = field(default_factory=list)
    decision_points: list[DecisionPoint] = field(default_factory=list)
    cutoff_points: list[CutoffPoint] = field(default_factory=list)
    vehicle_access_points: list[VehicleAccessPoint] = field(default_factory=list)
    image_evidence: list[ImageEvidence] = field(default_factory=list)
    evidence: list[EvidenceReference] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)


@dataclass
class RouteInfo:
    name: str = ""
    location: str = ""
    total_distance_km: float = 0.0
    total_elevation_gain_m: int = 0
    total_elevation_loss_m: int = 0
    difficulty_grade: str = ""
    difficulty_score: float = 0.0
    route_type: str = ""  # "环线" / "穿越" / "往返" / "City walk"
    is_heavy_pack: bool = False
    start_point: CoordinateInfo = field(default_factory=CoordinateInfo)
    end_point: CoordinateInfo = field(default_factory=CoordinateInfo)
    segments: list[RouteSegment] = field(default_factory=list)
    surface_summary: str = ""
    special_hazards: list[str] = field(default_factory=list)
    bailout_routes: list[str] = field(default_factory=list)
    gps_track_links: list[str] = field(default_factory=list)
    signal_coverage: str = ""
    scenery_highlights: str = ""
    history_culture: str = ""
    suitability: str = ""


@dataclass
class LeaderInfo:
    name: str
    role: str  # "主领队" / "副领队" / "实习领队"
    department: str = ""
    email: str = ""
    phone: str = ""
    bio: str = ""


@dataclass
class ActivityInfo:
    name: str = ""
    date: str = ""
    day_of_week: str = ""
    duration_type: str = ""  # "半日" / "一日" / "两日" / "多日"
    has_off_campus_guests: bool = False
    meeting_points: list[MeetingPoint] = field(default_factory=list)
    transport_mode: str = "包车"
    registration_start: str = ""
    registration_end: str = ""
    refund_deadline: str = ""


@dataclass
class CostBreakdown:
    bus_fee: float = 0
    leader_subsidy: float = 0
    free_spots: float = 0
    ribbon: float = 5
    insurance: float = 2
    other: str = ""


@dataclass
class OrganizationInfo:
    unit_name: str = "北京大学学生徒步越野协会"
    leaders: list[LeaderInfo] = field(default_factory=list)
    max_participants: int = 40
    member_cost: float = 0
    non_member_surcharge: float = 10
    cost_breakdown: CostBreakdown = field(default_factory=CostBreakdown)
    cost_includes: list[str] = field(default_factory=list)
    cost_excludes: list[str] = field(default_factory=list)
    schedule: list[ScheduleItem] = field(default_factory=list)
    leader_ratio: str = ""


@dataclass
class RiskItem:
    seq: int
    location: str
    risk_cause: str
    risk_level: str
    mitigation: str
    notes: str = ""


@dataclass
class GearItem:
    category: str  # "必备" / "强烈推荐" / "可选" / "按季节"
    name: str
    notes: str = ""


@dataclass
class PolicyInfo:
    border_permit: str = ""       # 边防证/入山证要求
    ticket_price: str = ""        # 景区门票价格
    student_ticket_policy: str = ""  # 学生票政策
    reservation_required: str = ""   # 是否需要预约/限流
    other_policies: str = ""         # 其他政策(无人机等)
    info_date: str = ""              # 信息获取日期


@dataclass
class ScenicSpot:
    name: str = ""
    ticket_price: str = ""          # 全价
    student_ticket_price: str = ""  # 学生票
    estimated_duration: str = ""    # 预计停留时间
    notes: str = ""


@dataclass
class FreeTour:
    location: str = ""
    tour_time: str = ""          # 讲解时间段
    meeting_point: str = ""      # 集合点
    need_reservation: str = ""   # 是否需要预约
    notes: str = ""


@dataclass
class PublicPerformance:
    name: str = ""
    performance_time: str = ""   # 演出时间
    location: str = ""
    cost: str = ""               # 费用(免费/价格)
    notes: str = ""


@dataclass
class TrailResearchData:
    activity: ActivityInfo = field(default_factory=ActivityInfo)
    route: RouteInfo = field(default_factory=RouteInfo)
    route_network: RouteNetwork = field(default_factory=RouteNetwork)
    organization: OrganizationInfo = field(default_factory=OrganizationInfo)
    policy: PolicyInfo = field(default_factory=PolicyInfo)
    risks: list[RiskItem] = field(default_factory=list)
    gear: list[GearItem] = field(default_factory=list)
    scenic_spots: list[ScenicSpot] = field(default_factory=list)  # City walk 途经景点
    free_tours: list[FreeTour] = field(default_factory=list)      # 免费讲解/导览
    public_performances: list[PublicPerformance] = field(default_factory=list)  # 公共演出
    registration_notes: str = ""
    references_links: list[str] = field(default_factory=list)

    def calc_difficulty_score(self) -> float:
        return self.route.total_distance_km + self.route.total_elevation_gain_m / 100.0

    def calc_difficulty_grade(self) -> str:
        score = self.calc_difficulty_score()
        tiers = ["休闲", "初级", "中级", "高级", "超高级"]

        if score < 12:
            base_tier = 0
        elif score < 20:
            base_tier = 1
        elif score < 35:
            base_tier = 2
        elif score < 50:
            base_tier = 3
        else:
            base_tier = 4

        hazard_count = len(self.route.special_hazards)
        bump = 0
        if 1 <= hazard_count <= 2:
            bump = 1
        elif hazard_count > 2:
            bump = 2

        if self.route.is_heavy_pack:
            bump += 1

        final_tier = min(base_tier + bump, 4)
        return tiers[final_tier]

    def to_json(self, filepath: str):
        import json
        from dataclasses import asdict
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, filepath: str) -> "TrailResearchData":
        import json

        with open(filepath, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        def _dict_to_dataclass(dc, d):
            field_names = {f.name for f in dc.__dataclass_fields__.values()}
            unknown = set(d.keys()) - field_names
            if unknown:
                warnings.warn(f"Unknown keys in {dc.__name__} ignored: {unknown}")
            kwargs = {}
            for k, v in d.items():
                if k in field_names:
                    kwargs[k] = v
            return dc(**kwargs)

        activity = _dict_to_dataclass(ActivityInfo, raw.get("activity", {}))
        activity.meeting_points = [
            _dict_to_dataclass(MeetingPoint, mp)
            for mp in raw.get("activity", {}).get("meeting_points", [])
        ]

        route = _dict_to_dataclass(RouteInfo, raw.get("route", {}))
        route.start_point = _dict_to_dataclass(CoordinateInfo, raw.get("route", {}).get("start_point", {}))
        route.end_point = _dict_to_dataclass(CoordinateInfo, raw.get("route", {}).get("end_point", {}))
        route.segments = [_dict_to_dataclass(RouteSegment, s) for s in raw.get("route", {}).get("segments", [])]

        network_raw = raw.get("route_network", {})
        route_network = _dict_to_dataclass(RouteNetwork, network_raw)
        route_network.state = _dict_to_dataclass(VerificationState, network_raw.get("state", {}))
        route_network.team_profile = _dict_to_dataclass(TeamProfile, network_raw.get("team_profile", {}))
        route_network.nodes = []
        for node_raw in network_raw.get("nodes", []):
            node = _dict_to_dataclass(RouteNode, node_raw)
            node.coordinate = _dict_to_dataclass(CoordinateInfo, node_raw.get("coordinate", {}))
            node.state = _dict_to_dataclass(VerificationState, node_raw.get("state", {}))
            route_network.nodes.append(node)
        route_network.edges = []
        for edge_raw in network_raw.get("edges", []):
            edge = _dict_to_dataclass(RouteEdge, edge_raw)
            edge.difficulty = _dict_to_dataclass(EdgeDifficulty, edge_raw.get("difficulty", {}))
            edge.time_estimate = _dict_to_dataclass(TimeEstimate, edge_raw.get("time_estimate", {}))
            edge.state = _dict_to_dataclass(VerificationState, edge_raw.get("state", {}))
            edge.geometry_points = [
                _dict_to_dataclass(GeoPoint, item)
                for item in edge_raw.get("geometry_points", [])
            ]
            route_network.edges.append(edge)
        route_network.track_sources = [
            _dict_to_dataclass(TrackSource, item)
            for item in network_raw.get("track_sources", [])
        ]
        route_network.track_segment_observations = [
            _dict_to_dataclass(TrackSegmentObservation, item)
            for item in network_raw.get("track_segment_observations", [])
        ]
        route_network.decision_points = []
        for decision_raw in network_raw.get("decision_points", []):
            decision = _dict_to_dataclass(DecisionPoint, decision_raw)
            decision.state = _dict_to_dataclass(VerificationState, decision_raw.get("state", {}))
            route_network.decision_points.append(decision)
        route_network.cutoff_points = []
        for cutoff_raw in network_raw.get("cutoff_points", []):
            cutoff = _dict_to_dataclass(CutoffPoint, cutoff_raw)
            cutoff.state = _dict_to_dataclass(VerificationState, cutoff_raw.get("state", {}))
            route_network.cutoff_points.append(cutoff)
        route_network.vehicle_access_points = []
        for access_raw in network_raw.get("vehicle_access_points", []):
            access = _dict_to_dataclass(VehicleAccessPoint, access_raw)
            access.state = _dict_to_dataclass(VerificationState, access_raw.get("state", {}))
            route_network.vehicle_access_points.append(access)
        route_network.image_evidence = [
            _dict_to_dataclass(ImageEvidence, item)
            for item in network_raw.get("image_evidence", [])
        ]
        route_network.evidence = [
            _dict_to_dataclass(EvidenceReference, item)
            for item in network_raw.get("evidence", [])
        ]

        org_raw = raw.get("organization", {})
        org = _dict_to_dataclass(OrganizationInfo, org_raw)
        org.leaders = [_dict_to_dataclass(LeaderInfo, l) for l in org_raw.get("leaders", [])]
        org.cost_breakdown = _dict_to_dataclass(CostBreakdown, org_raw.get("cost_breakdown", {}))
        org.schedule = [_dict_to_dataclass(ScheduleItem, s) for s in org_raw.get("schedule", [])]

        policy = _dict_to_dataclass(PolicyInfo, raw.get("policy", {}))

        risks = [_dict_to_dataclass(RiskItem, r) for r in raw.get("risks", [])]
        gear = [_dict_to_dataclass(GearItem, g) for g in raw.get("gear", [])]
        scenic_spots = [_dict_to_dataclass(ScenicSpot, s) for s in raw.get("scenic_spots", [])]
        free_tours = [_dict_to_dataclass(FreeTour, t) for t in raw.get("free_tours", [])]
        public_performances = [_dict_to_dataclass(PublicPerformance, p) for p in raw.get("public_performances", [])]

        return cls(
            activity=activity,
            route=route,
            route_network=route_network,
            organization=org,
            policy=policy,
            risks=risks,
            gear=gear,
            scenic_spots=scenic_spots,
            free_tours=free_tours,
            public_performances=public_performances,
            registration_notes=raw.get("registration_notes", ""),
            references_links=raw.get("references_links", []),
        )
