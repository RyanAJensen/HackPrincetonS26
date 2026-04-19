from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import ceil
from typing import Any


def _normalize_name(value: str | None) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in (value or "")).split()


def _name_key(value: str | None) -> str:
    return " ".join(_normalize_name(value))


_HOSPITAL_STOPWORDS = {
    "medical",
    "center",
    "hospital",
    "university",
    "of",
    "the",
    "campus",
}


def _hospital_tokens(value: str | None) -> set[str]:
    return {token for token in _normalize_name(value) if token not in _HOSPITAL_STOPWORDS}


def _hospital_key(value: str | None, existing: dict[str, dict[str, Any]]) -> str:
    exact_key = _name_key(value)
    if exact_key in existing:
        return exact_key
    tokens = _hospital_tokens(value)
    if not tokens:
        return exact_key
    for candidate_key, candidate in existing.items():
        candidate_tokens = _hospital_tokens(candidate.get("name"))
        if not candidate_tokens:
            continue
        overlap = tokens & candidate_tokens
        if len(overlap) >= 2 and len(overlap) == min(len(tokens), len(candidate_tokens)):
            return candidate_key
        if len(overlap) >= 2 and (len(overlap) / max(1, min(len(tokens), len(candidate_tokens)))) >= 0.75:
            return candidate_key
    return exact_key


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _status(value: str | None) -> str:
    raw = (value or "normal").strip().lower()
    if raw in {"normal", "elevated", "critical", "diversion"}:
        return raw
    return "normal"


def _trauma_level(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    return raw or None


def _safe_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _compact(text: str | None, limit: int = 120) -> str:
    value = " ".join((text or "").split())
    return value[:limit]


def _primary_destination(assignments: list[dict[str, Any]]) -> str:
    for assignment in assignments:
        if "critical" in _safe_list(assignment.get("patient_types")):
            return str(assignment.get("hospital") or "best available receiving facility")
    if assignments:
        return str(assignments[0].get("hospital") or "best available receiving facility")
    return "best available receiving facility"


def _alternate_destination(assignments: list[dict[str, Any]], primary_destination: str) -> str:
    for assignment in assignments:
        hospital = str(assignment.get("hospital") or "")
        if hospital and hospital != primary_destination:
            return hospital
    return primary_destination


def _find_resource_owner(resources: list[dict[str, Any]], keywords: tuple[str, ...]) -> str | None:
    for resource in resources:
        if not resource.get("available", True):
            continue
        haystack = " ".join(
            part for part in (
                str(resource.get("name") or ""),
                str(resource.get("role") or ""),
                str(resource.get("ics_group") or ""),
            )
            if part
        ).lower()
        if any(keyword in haystack for keyword in keywords):
            return str(resource.get("name") or "")
    return None


def _role_entry(
    role: str,
    responsibilities: list[str],
    *,
    assigned_to: str | None = None,
    agency: str | None = None,
    active: bool = True,
) -> dict[str, Any]:
    return {
        "role": role,
        "assigned_to": assigned_to,
        "agency": agency,
        "active": active,
        "responsibilities": responsibilities[:4],
    }


def _count_state(parsed: dict[str, Any]) -> dict[str, int]:
    medical = parsed.get("medical_impact") or {}
    critical = max(_int(parsed.get("critical")), _int(medical.get("critical")))
    moderate = max(_int(parsed.get("moderate")), _int(medical.get("moderate")))
    minor = max(_int(parsed.get("minor")), _int(medical.get("minor")))
    total = _int(parsed.get("incoming_patient_count"), critical + moderate + minor)
    if total < critical + moderate + minor:
        total = critical + moderate + minor
    if total > critical + moderate + minor:
        moderate += total - (critical + moderate + minor)
    return {
        "total": total,
        "critical": critical,
        "moderate": moderate,
        "minor": minor,
    }


def _merge_hospitals(
    ext_ctx: dict[str, Any],
    hospital_capacities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mapping_hospitals = _safe_list(((ext_ctx.get("mapping") or {}).get("hospitals")))
    merged: dict[str, dict[str, Any]] = {}

    for item in mapping_hospitals:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or "Receiving facility"
        merged[_hospital_key(name, merged)] = {
            "name": name,
            "distance_mi": _float(item.get("distance_mi")),
            "trauma_level": _trauma_level(item.get("trauma_level")),
            "status": "normal",
            "available_beds": None,
            "total_beds": None,
            "specialty": None,
        }

    for item in hospital_capacities:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or "Receiving facility"
        key = _hospital_key(name, merged)
        merged.setdefault(
            key,
            {
                "name": name,
                "distance_mi": _float(item.get("distance_mi")),
                "trauma_level": _trauma_level(item.get("specialty")),
                "status": "normal",
                "available_beds": None,
                "total_beds": None,
                "specialty": None,
            },
        )
        merged[key]["status"] = _status(item.get("status"))
        merged[key]["available_beds"] = _int(item.get("available_beds"), 0) if item.get("available_beds") is not None else None
        merged[key]["total_beds"] = _int(item.get("total_beds"), 0) if item.get("total_beds") is not None else None
        merged[key]["specialty"] = item.get("specialty")
        if merged[key].get("distance_mi") is None:
            merged[key]["distance_mi"] = _float(item.get("distance_mi"))

    facilities = list(merged.values())
    if not facilities:
        facilities = [
            {
                "name": "Nearest available receiving facility",
                "distance_mi": None,
                "trauma_level": None,
                "status": "normal",
                "available_beds": None,
                "total_beds": None,
                "specialty": None,
            }
        ]
    return facilities


def _route_strings(ext_ctx: dict[str, Any], parsed: dict[str, Any]) -> tuple[str, str, list[str], dict[str, Any]]:
    routing = ((ext_ctx.get("mapping") or {}).get("routing")) or {}
    water_risk = (((ext_ctx.get("water") or {}).get("risk")) or {})
    parsed_notes = " ".join(
        str(value)
        for value in (
            parsed.get("transport_status"),
            parsed.get("location_notes"),
            parsed.get("infrastructure_impact"),
        )
        if value
    ).lower()
    hazards = " ".join(str(item) for item in _safe_list(parsed.get("key_hazards"))).lower()

    primary_steps = _safe_list(routing.get("primary_route_steps"))
    alternate_steps = _safe_list(routing.get("alternate_route_steps"))
    primary_blocked = any(
        token in parsed_notes
        for token in (
            "impassable to standard ambulances",
            "primary corridor impassable",
            "primary access corridor impaired",
            "blocked roadway",
        )
    )
    if not primary_blocked and "impassable" in parsed_notes and any(
        token in parsed_notes for token in ("road", "route", "corridor", "ambulance", "access")
    ):
        primary_blocked = True
    primary_route = (
        "Primary corridor reported impassable to standard ambulances"
        if primary_blocked
        else " > ".join(primary_steps[:3]) if primary_steps else "Use safest confirmed primary corridor"
    )
    alternate_route = (
        " > ".join(alternate_steps[:3])
        if alternate_steps
        else "Use alternate corridor if flooding or blockage affects primary route"
    )
    route_constraints: list[str] = []

    duration = _float(routing.get("primary_duration_min"))
    if primary_blocked:
        route_constraints.append("Primary access corridor is impassable to standard ambulances")
    elif duration is not None:
        if duration >= 25:
            route_constraints.append(f"Primary route travel time is extended at ~{int(duration)} min")
    else:
        route_constraints.append("Primary route travel time is unconfirmed")

    if any(token in hazards or token in parsed_notes for token in ("flood", "blocked", "impassable", "bridge", "surge")):
        if primary_blocked:
            route_constraints.append("Use elevated or alternate access points until flood levels recede")
        else:
            route_constraints.append("Primary access corridor may degrade due to reported scene hazards")
    if water_risk.get("severity") in {"moderate", "high"}:
        for signal in _safe_list(water_risk.get("signals"))[:2]:
            route_constraints.append(str(signal))
    if "second water surge" in parsed_notes or "secondary water surge" in parsed_notes or "surge" in hazards:
        route_constraints.append("Secondary water surge may cut remaining access within minutes")
    if not alternate_steps:
        route_constraints.append("Alternate route is not confirmed by routing service")

    return primary_route, alternate_route, route_constraints[:4], {
        "primary_blocked": primary_blocked,
        "alternate_confirmed": bool(alternate_steps),
    }


def _resource_summary(resources: list[dict[str, Any]], critical: int, total: int) -> tuple[str, list[str]]:
    available = [r for r in resources if r.get("available", True)]
    roles = [str(r.get("role", "")).lower() for r in available]
    ems_units = sum(1 for role in roles if any(token in role for token in ("ems", "medic", "ambulance", "als")))
    rescue_units = sum(1 for role in roles if any(token in role for token in ("fire", "rescue", "ladder")))
    required_units = max(1, critical + ceil(max(total - critical, 0) / 3))

    gaps: list[str] = []
    if critical > 0 and ems_units == 0:
        gaps.append("No dedicated EMS/ALS transport unit confirmed for critical patients")
    if total > 0 and rescue_units == 0:
        gaps.append("No rescue/fire unit confirmed for scene access support")

    if ems_units >= required_units:
        adequacy = "sufficient"
    elif ems_units >= max(1, required_units - 1):
        adequacy = "strained"
    else:
        adequacy = "insufficient"
        gaps.append("Available transport units may be insufficient for projected patient load")

    return adequacy, gaps[:3]


def _resource_buckets(resources: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str], list[str]]:
    assigned: list[str] = []
    staged: list[str] = []
    requested: list[str] = []
    out_of_service: list[str] = []
    for resource in resources:
        name = str(resource.get("name") or "Resource")
        status = str(resource.get("deployment_status") or "").strip().lower()
        if status == "assigned":
            assigned.append(name)
        elif status == "staged":
            staged.append(name)
        elif status == "requested":
            requested.append(name)
        elif status in {"unavailable", "out_of_service"} or not resource.get("available", True):
            out_of_service.append(name)
    return assigned[:6], staged[:6], requested[:6], out_of_service[:6]


def _access_constraints(parsed: dict[str, Any], route_constraints: list[str]) -> list[str]:
    constraints = route_constraints[:]
    for key in ("transport_status", "location_notes", "infrastructure_impact"):
        value = parsed.get(key)
        if value:
            constraints.append(str(value))
    return list(dict.fromkeys(constraints))[:4]


def _command_structure(
    incident_type: str,
    counts: dict[str, int],
    parsed: dict[str, Any],
    access_constraints: list[str],
    resources: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    hazards = " ".join(str(item).lower() for item in _safe_list(parsed.get("key_hazards")))
    immediate_threat = bool(parsed.get("immediate_life_safety_threat"))
    total = counts["total"]
    resource_roles = {str(resource.get("role", "")).lower() for resource in resources if resource.get("available", True)}
    multi_agency = sum(
        1
        for predicate in (
            any(any(token in role for token in ("ems", "medic", "ambulance")) for role in resource_roles),
            any(any(token in role for token in ("fire", "rescue", "ladder")) for role in resource_roles),
            any(any(token in role for token in ("law", "sheriff", "police")) for role in resource_roles),
            any(any(token in role for token in ("hazmat", "public works", "utility", "eoc")) for role in resource_roles),
        )
        if predicate
    )

    complexity_tokens = ("hazmat", "swift water", "flood", "collapse", "fire", "security", "active threat", "power")
    complex_scene = immediate_threat or counts["critical"] > 0 or total >= 5 or any(token in hazards for token in complexity_tokens)
    constrained_scene = len(access_constraints) >= 2

    if not complex_scene and total <= 1:
        command_mode = "investigative"
    elif not constrained_scene and total <= 3 and counts["critical"] == 0:
        command_mode = "fast_attack"
    else:
        command_mode = "command"

    unified_command_recommended = multi_agency >= 3 or any(
        token in incident_type.lower()
        for token in ("hazmat", "security", "infrastructure", "flood", "storm")
    )
    safety_officer_recommended = command_mode == "command" and (
        complex_scene or constrained_scene or total >= 5
    )
    staging_area = (
        f"Stage one access-control point short of {parsed.get('confirmed_location') or 'the incident location'}"
        if total >= 3 or len(resources) >= 4 or constrained_scene
        else ""
    )[:120]
    transport_group_active = total >= 3 or counts["critical"] > 0 or len(assignments) >= 2
    triage_group_active = total >= 2 or counts["critical"] > 0
    treatment_group_active = counts["critical"] > 0 or counts["moderate"] > 0
    public_information_officer_recommended = unified_command_recommended or total >= 8 or any(
        token in incident_type.lower() for token in ("evacuation", "storm", "flood", "hazmat")
    )
    liaison_officer_recommended = unified_command_recommended or multi_agency >= 3
    operations_section_active = command_mode == "command" or total > 0
    planning_section_active = command_mode == "command" or total >= 3 or constrained_scene
    logistics_section_active = bool(resources) or bool(staging_area)
    finance_admin_section_active = total >= 10 or (counts["critical"] >= 2 and constrained_scene)

    rationale = []
    rationale.append(f"Command mode set to {command_mode} based on patient load, hazards, and access")
    if unified_command_recommended:
        rationale.append("Unified Command recommended because the incident spans multiple agencies/functions")
    if safety_officer_recommended:
        rationale.append("Safety Officer recommended because hazards and tempo increase responder risk")
    if staging_area:
        rationale.append("Staging is recommended to protect access and maintain span of control")

    return {
        "command_mode": command_mode,
        "command_post_established": command_mode == "command",
        "unified_command_recommended": unified_command_recommended,
        "safety_officer_recommended": safety_officer_recommended,
        "public_information_officer_recommended": public_information_officer_recommended,
        "liaison_officer_recommended": liaison_officer_recommended,
        "operations_section_active": operations_section_active,
        "planning_section_active": planning_section_active,
        "logistics_section_active": logistics_section_active,
        "finance_admin_section_active": finance_admin_section_active,
        "triage_group_active": triage_group_active,
        "treatment_group_active": treatment_group_active,
        "staging_area": staging_area,
        "transport_group_active": transport_group_active,
        "rationale": rationale[:4],
    }


def _operational_objectives(
    counts: dict[str, int],
    assignments: list[dict[str, Any]],
    primary_route: str,
    risk: dict[str, Any],
    command_structure: dict[str, Any],
    route_status: dict[str, Any],
) -> list[str]:
    primary_destination = _primary_destination(assignments)
    objectives = [
        f"Life safety: move {counts['critical']} critical patients first to {primary_destination}",
        (
            "Incident stabilization: establish and protect an alternate transport corridor"
            if route_status.get("primary_blocked")
            else f"Incident stabilization: keep primary corridor usable ({primary_route[:48]})"
        ),
        "Responder safety: control access, hazards, and ambulance ingress/egress",
    ]
    if command_structure.get("staging_area"):
        objectives.append("Establish staging and maintain span of control for incoming units")
    if risk.get("resource_adequacy") != "sufficient":
        objectives.append("Request additional transport capability before throughput degrades further")
    return objectives[:4]


def _owned_actions(
    command_structure: dict[str, Any],
    counts: dict[str, int],
    assignments: list[dict[str, Any]],
    primary_route: str,
    alternate_route: str,
    resource_gaps: list[str],
    route_status: dict[str, Any],
) -> dict[str, list[str]]:
    primary_destination = _primary_destination(assignments)
    alternate_destination = _alternate_destination(assignments, primary_destination)
    owned = {
        "command": [
            f"Operate in {command_structure['command_mode']} mode and confirm command post location",
            "Publish top 3 operational priorities and replan triggers",
        ],
        "operations": [
            "Rescue, triage, and move highest-acuity patients first",
            (
                f"Do not use blocked primary corridor; route units through alternate access: {alternate_route[:72]}"
                if route_status.get("primary_blocked")
                else f"Keep primary access route open: {primary_route[:72]}"
            ),
        ],
        "planning": [
            "Maintain patient count, triage status, and incident timeline",
            "Update recommendations as route, weather, or destination status changes",
        ],
        "logistics": [
            command_structure.get("staging_area") or "Prepare staging area and route support assets",
            "Support corridor control, PPE, lighting, and transport readiness",
        ],
        "safety": [
            "Control hazard zones and verify responder PPE/work-rest cycle",
            "Monitor for route degradation and scene safety changes",
        ],
        "triage": [
            f"Perform START-style triage and prepare {counts['critical']} immediate transport(s)",
        ],
        "transport": [
            f"Send highest-acuity patients to {primary_destination}",
            (
                f"Use alternate corridor and {alternate_destination} if the blocked primary route delays transport"
                if route_status.get("primary_blocked")
                else f"Use {alternate_destination} / {alternate_route[:56]} if primary destination or route degrades"
            ),
        ],
    }
    if command_structure.get("unified_command_recommended"):
        owned["command"].append("Form Unified Command with partner agencies as they arrive")
    if command_structure.get("safety_officer_recommended"):
        owned["safety"].insert(0, "Assign or recommend a Safety Officer now")
    if resource_gaps:
        owned["logistics"].append(resource_gaps[0])
    return {key: values[:3] for key, values in owned.items() if values}


def _ics_organization(
    command_structure: dict[str, Any],
    resources: list[dict[str, Any]],
    counts: dict[str, int],
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    primary_destination = _primary_destination(assignments)
    command_roles = [
        _role_entry(
            "Incident Commander",
            ["Establish command", "Approve priorities", "Assign supervisory roles"],
            assigned_to=_find_resource_owner(resources, ("command", "chief", "supervisor", "eoc", "sheriff")),
            active=True,
        ),
        _role_entry(
            "Safety Officer",
            ["Control hazard zones", "Approve responder access controls", "Monitor safety triggers"],
            assigned_to=_find_resource_owner(resources, ("safety",)),
            active=bool(command_structure.get("safety_officer_recommended")),
        ),
        _role_entry(
            "Public Information Officer",
            ["Release public messaging", "Coordinate public protective actions"],
            assigned_to=_find_resource_owner(resources, ("public information", "pio")),
            active=bool(command_structure.get("public_information_officer_recommended")),
        ),
        _role_entry(
            "Liaison Officer",
            ["Coordinate partner agencies", "Support unified command interfaces"],
            assigned_to=_find_resource_owner(resources, ("liaison", "eoc")),
            active=bool(command_structure.get("liaison_officer_recommended")),
        ),
        _role_entry(
            "Operations Section Chief",
            ["Direct field operations", "Own rescue, triage, treatment, transport"],
            assigned_to=_find_resource_owner(resources, ("operations", "fire", "rescue", "ems")),
            active=bool(command_structure.get("operations_section_active")),
        ),
        _role_entry(
            "Planning Section Chief",
            ["Maintain common operating picture", "Track incident log and replan triggers"],
            assigned_to=_find_resource_owner(resources, ("planning", "eoc")),
            active=bool(command_structure.get("planning_section_active")),
        ),
        _role_entry(
            "Logistics Section Chief",
            ["Manage staging, PPE, and route support", "Track available/staged resources"],
            assigned_to=_find_resource_owner(resources, ("logistics", "public works", "utility")),
            active=bool(command_structure.get("logistics_section_active")),
        ),
        _role_entry(
            "Finance / Admin",
            ["Track extended incident costs and mutual-aid admin needs"],
            assigned_to=_find_resource_owner(resources, ("finance", "admin")),
            active=bool(command_structure.get("finance_admin_section_active")),
        ),
        _role_entry(
            "Triage Unit Leader",
            [f"Triage {counts['total']} known patients", "Update acuity counts to Planning"],
            assigned_to=_find_resource_owner(resources, ("ems", "medic", "ambulance")),
            active=bool(command_structure.get("triage_group_active")),
        ),
        _role_entry(
            "Treatment Unit Leader",
            ["Establish treatment area", "Stabilize patients before transport"],
            assigned_to=_find_resource_owner(resources, ("ems", "medic", "als")),
            active=bool(command_structure.get("treatment_group_active")),
        ),
        _role_entry(
            "Transport Officer",
            [f"Coordinate destinations including {primary_destination}", "Manage ambulance loading order"],
            assigned_to=_find_resource_owner(resources, ("transport", "ambulance", "trauma coordinator", "ems")),
            active=bool(command_structure.get("transport_group_active")),
        ),
    ]
    if command_structure.get("unified_command_recommended"):
        command_roles.insert(
            1,
            _role_entry(
                "Unified Command",
                ["Coordinate multi-agency priorities", "Resolve cross-jurisdiction conflicts"],
                assigned_to=None,
                active=True,
            ),
        )
    return [role for role in command_roles if role.get("active")]


def _structured_owned_actions(
    command_structure: dict[str, Any],
    counts: dict[str, int],
    assignments: list[dict[str, Any]],
    primary_route: str,
    alternate_route: str,
    resource_gaps: list[str],
    route_status: dict[str, Any],
) -> list[dict[str, Any]]:
    primary_destination = _primary_destination(assignments)
    alternate_destination = _alternate_destination(assignments, primary_destination)
    actions = [
        {
            "description": f"Establish {command_structure['command_mode']} mode and confirm command post",
            "owner_role": "Incident Commander",
            "operational_group": "command",
            "timeframe": "0-5 min",
            "priority": 1,
            "contingency": "Expand command if additional agencies or patient load arrive",
            "critical": True,
        },
        {
            "description": "Publish initial incident objectives and assign field supervisors",
            "owner_role": "Incident Commander",
            "operational_group": "command",
            "timeframe": "0-10 min",
            "priority": 1,
            "contingency": "Escalate to Unified Command if agency conflicts emerge",
            "critical": True,
        },
        {
            "description": "Control hazard zones and define responder access restrictions",
            "owner_role": "Safety Officer" if command_structure.get("safety_officer_recommended") else "Incident Commander",
            "operational_group": "safety",
            "timeframe": "0-10 min",
            "priority": 1,
            "contingency": "Stop entry if hazards worsen or route becomes unsafe",
            "critical": True,
        },
        {
            "description": f"Perform triage and move critical patients first toward {primary_destination}",
            "owner_role": "Triage Unit Leader",
            "operational_group": "triage",
            "timeframe": "0-10 min",
            "priority": 1,
            "contingency": "Re-tag and notify Planning if patient count or acuity changes",
            "critical": True,
        },
        {
            "description": "Stand up treatment area and stabilize immediate / delayed patients",
            "owner_role": "Treatment Unit Leader",
            "operational_group": "treatment",
            "timeframe": "0-15 min",
            "priority": 2,
            "contingency": "Shift treatment area if access corridor or hazards change",
            "critical": counts["critical"] > 0 or counts["moderate"] > 0,
        },
        {
            "description": (
                f"Coordinate transport destinations and ambulance loading via alternate access: {alternate_route[:72]}"
                if route_status.get("primary_blocked")
                else f"Coordinate transport destinations and ambulance loading via {primary_route[:72]}"
            ),
            "owner_role": "Transport Officer",
            "operational_group": "transport",
            "timeframe": "0-15 min",
            "priority": 1,
            "contingency": (
                f"Hold transport until alternate corridor is confirmed; use {alternate_destination} if route or capacity degrades"
                if route_status.get("primary_blocked")
                else f"Use {alternate_destination} via {alternate_route[:72]} if route or capacity degrades"
            ),
            "critical": True,
        },
        {
            "description": "Maintain the incident log, patient count, and change summary",
            "owner_role": "Planning Section Chief",
            "operational_group": "planning",
            "timeframe": "0-30 min",
            "priority": 2,
            "contingency": "Issue updated IAP when bottlenecks or assignments change",
            "critical": True,
        },
        {
            "description": "Manage staging, route support assets, and resource tracking",
            "owner_role": "Logistics Section Chief",
            "operational_group": "logistics",
            "timeframe": "0-30 min",
            "priority": 2,
            "contingency": "Request additional transport or support units if staged assets drop",
            "critical": False,
        },
    ]
    if command_structure.get("public_information_officer_recommended"):
        actions.append(
            {
                "description": "Release approved public protective-action messaging",
                "owner_role": "Public Information Officer",
                "operational_group": "communications",
                "timeframe": "10-30 min",
                "priority": 3,
                "contingency": "Hold release if Unified Command messaging is not aligned",
                "critical": False,
            }
        )
    if command_structure.get("liaison_officer_recommended"):
        actions.append(
            {
                "description": "Coordinate hospital, law, fire, and EOC partner updates",
                "owner_role": "Liaison Officer",
                "operational_group": "liaison",
                "timeframe": "10-30 min",
                "priority": 2,
                "contingency": "Escalate unresolved agency conflicts to Unified Command",
                "critical": False,
            }
        )
    if command_structure.get("unified_command_recommended"):
        actions.append(
            {
                "description": "Form Unified Command and align agency priorities",
                "owner_role": "Incident Commander",
                "operational_group": "command",
                "timeframe": "0-15 min",
                "priority": 1,
                "contingency": "Keep command-mode structure until partner agencies arrive",
                "critical": True,
            }
        )
    if resource_gaps:
        actions.append(
            {
                "description": _compact(resource_gaps[0]),
                "owner_role": "Logistics Section Chief",
                "operational_group": "logistics",
                "timeframe": "0-20 min",
                "priority": 2,
                "contingency": "Request mutual aid if gap persists",
                "critical": True,
            }
        )
    return actions[:12]


def _span_of_control(
    command_structure: dict[str, Any],
    resources: list[dict[str, Any]],
    structured_actions: list[dict[str, Any]],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    ic_direct_reports = sum(
        1
        for flag in (
            command_structure.get("safety_officer_recommended"),
            command_structure.get("public_information_officer_recommended"),
            command_structure.get("liaison_officer_recommended"),
            command_structure.get("operations_section_active"),
            command_structure.get("planning_section_active"),
            command_structure.get("logistics_section_active"),
            command_structure.get("finance_admin_section_active"),
        )
        if flag
    )
    if ic_direct_reports > 5:
        warnings.append(
            {
                "supervisor_role": "Incident Commander",
                "direct_reports": ic_direct_reports,
                "recommended_structure": "Assign or reinforce section chiefs and move medical branches under Operations",
                "reason": "Command span is approaching or exceeding ICS best-practice supervision limits",
                "severity": "warning",
            }
        )
    medical_direct_reports = sum(
        1
        for flag in (
            command_structure.get("triage_group_active"),
            command_structure.get("treatment_group_active"),
            command_structure.get("transport_group_active"),
        )
        if flag
    )
    if medical_direct_reports >= 3 and counts["total"] >= 4:
        warnings.append(
            {
                "supervisor_role": "Operations Section Chief",
                "direct_reports": medical_direct_reports,
                "recommended_structure": "Establish a Medical Group Supervisor over triage, treatment, and transport",
                "reason": "Medical operations are split across multiple functions and should be coordinated under one supervisor",
                "severity": "warning",
            }
        )
    assigned_like = sum(
        1 for resource in resources
        if str(resource.get("deployment_status") or "").lower() in {"assigned", "staged"} and resource.get("available", True)
    )
    if assigned_like >= 6 and not command_structure.get("staging_area"):
        warnings.append(
            {
                "supervisor_role": "Logistics Section Chief",
                "direct_reports": assigned_like,
                "recommended_structure": "Create a staging manager / area manager function",
                "reason": "Multiple units are active without a defined staging area",
                "severity": "advisory",
            }
        )
    return warnings[:4]


def _accountability_report(
    structured_actions: list[dict[str, Any]],
    command_structure: dict[str, Any],
) -> dict[str, Any]:
    by_action: dict[str, set[str]] = defaultdict(set)
    unowned: list[str] = []
    duplicate: list[str] = []
    conflicting: list[str] = []
    issues: list[dict[str, Any]] = []
    for action in structured_actions:
        description = _compact(str(action.get("description") or ""), 160)
        owner_role = _compact(str(action.get("owner_role") or ""), 80)
        if not owner_role:
            unowned.append(description)
            issues.append(
                {
                    "kind": "unowned_action",
                    "severity": "critical" if action.get("critical") else "warning",
                    "message": "Critical action is missing an owner role" if action.get("critical") else "Action is missing an owner role",
                    "action_description": description,
                    "owner_role": None,
                }
            )
            continue
        key = _name_key(description)
        by_action[key].add(owner_role)
        if len(by_action[key]) > 1:
            conflicting.append(description)
        if description in duplicate:
            continue
        if sum(1 for item in structured_actions if _name_key(str(item.get("description") or "")) == key) > 1:
            duplicate.append(description)
    self_dispatch_risks: list[str] = []
    if not command_structure.get("command_post_established") and command_structure.get("command_mode") == "command":
        self_dispatch_risks.append("Expanded command recommended but command post is not yet established")
    status = "ok"
    if unowned or conflicting:
        status = "critical"
    elif duplicate or self_dispatch_risks:
        status = "warning"
    for description in conflicting:
        issues.append(
            {
                "kind": "conflicting_assignment",
                "severity": "warning",
                "message": "Action appears under more than one owner role",
                "action_description": description,
                "owner_role": None,
            }
        )
    for description in duplicate:
        issues.append(
            {
                "kind": "duplicate_assignment",
                "severity": "advisory",
                "message": "Action is duplicated and should be consolidated under one owner",
                "action_description": description,
                "owner_role": None,
            }
        )
    return {
        "status": status,
        "unowned_actions": unowned[:4],
        "conflicting_assignments": conflicting[:4],
        "duplicate_assignments": duplicate[:4],
        "self_dispatch_risks": self_dispatch_risks[:3],
        "issues": issues[:8],
    }


def _medical_operations(
    counts: dict[str, int],
    assignments: list[dict[str, Any]],
    alternate_route: str,
    route_status: dict[str, Any],
) -> dict[str, Any]:
    primary_destination = _primary_destination(assignments)
    alternate_destination = _alternate_destination(assignments, primary_destination)
    return {
        "triage": {
            "group_name": "Triage",
            "owner_role": "Triage Unit Leader",
            "objectives": [
                "Sort patients by immediate, delayed, and minor priority",
                "Report updated patient counts to Planning and Transport",
            ],
            "actions": [
                {
                    "description": f"Triage {counts['total']} known patients and identify immediate transports",
                    "owner_role": "Triage Unit Leader",
                    "operational_group": "triage",
                    "timeframe": "0-10 min",
                    "priority": 1,
                    "contingency": "Repeat triage if hazards change or new patients are found",
                    "critical": True,
                }
            ],
            "status": "active",
        },
        "treatment": {
            "group_name": "Treatment",
            "owner_role": "Treatment Unit Leader",
            "objectives": [
                "Stabilize critical and urgent patients before transport",
                "Separate treatment area from transport loading corridor",
            ],
            "actions": [
                {
                    "description": "Open treatment area and prepare immediate / delayed treatment tracks",
                    "owner_role": "Treatment Unit Leader",
                    "operational_group": "treatment",
                    "timeframe": "0-15 min",
                    "priority": 2,
                    "contingency": "Relocate treatment area if access corridor becomes unsafe",
                    "critical": counts["critical"] > 0 or counts["moderate"] > 0,
                }
            ],
            "status": "active" if counts["critical"] > 0 or counts["moderate"] > 0 else "monitoring",
        },
        "transport": {
            "group_name": "Transport",
            "owner_role": "Transport Officer",
            "objectives": [
                (
                    f"Send immediate patients to {primary_destination} via alternate access"
                    if route_status.get("primary_blocked")
                    else f"Send immediate patients to {primary_destination}"
                ),
                "Balance lower-acuity patients to preserve receiving capacity",
            ],
            "actions": [
                {
                    "description": (
                        f"Load and dispatch immediate patients to {primary_destination} using alternate access"
                        if route_status.get("primary_blocked")
                        else f"Load and dispatch immediate patients to {primary_destination}"
                    ),
                    "owner_role": "Transport Officer",
                    "operational_group": "transport",
                    "timeframe": "0-15 min",
                    "priority": 1,
                    "contingency": f"Switch to {alternate_destination} via {alternate_route[:72]} if destination or route fails",
                    "critical": True,
                }
            ],
            "status": "active",
        },
    }


def _incident_action_plan(
    command_structure: dict[str, Any],
    organization: list[dict[str, Any]],
    objectives: list[str],
    structured_actions: list[dict[str, Any]],
    risk: dict[str, Any],
    operational_period: str,
) -> dict[str, Any]:
    command_intent = (
        "Protect life safety, maintain command and transport control, and keep receiving capacity available"
    )
    communications_plan = [
        "Incident Commander briefs section leads on each plan change",
        "Planning updates the common operating picture and incident log",
        "Transport Officer updates receiving hospitals on destination and acuity changes",
        "Public Information Officer releases only command-approved public messaging",
    ]
    if command_structure.get("unified_command_recommended"):
        communications_plan.insert(1, "Unified Command resolves cross-agency conflicts before reassignment")
    responder_injury = [
        "Notify Incident Commander immediately if any responder is injured",
        "Safety Officer pauses unsafe operations and confirms access corridor",
        "Treatment Unit Leader stabilizes injured responder and Transport Officer assigns destination",
    ]
    return {
        "command_intent": command_intent,
        "current_objectives": objectives[:4],
        "organization": organization,
        "owned_actions": structured_actions[:10],
        "communications_plan": communications_plan[:4],
        "responder_injury_contingency": responder_injury,
        "degradation_triggers": list(dict.fromkeys((risk.get("replan_triggers") or risk.get("decision_triggers") or [])[:4])),
        "operational_period": operational_period or "Initial operational period",
    }


def _command_transfer_summary(
    command_structure: dict[str, Any],
    objectives: list[str],
    hazards: list[str],
    owned_actions: dict[str, list[str]],
    risk: dict[str, Any],
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "command_mode": command_structure.get("command_mode", ""),
        "current_strategy": objectives[0] if objectives else "Stabilize the incident and protect medical throughput",
        "active_groups": [group for group in owned_actions.keys() if group in {"command", "operations", "safety", "triage", "transport", "planning"}][:6],
        "top_hazards": [str(item) for item in hazards[:4]],
        "next_decisions": list(dict.fromkeys((risk.get("decision_triggers") or risk.get("replan_triggers") or [])[:4])),
        "resource_status": [
            f"{resource.get('name', 'Resource')}={str(resource.get('deployment_status') or 'available')}"
            for resource in resources[:6]
        ],
        "transfer_needs": [
            "Confirm command mode and current objectives",
            "Review active medical branches and reroute triggers",
            "Confirm staged, assigned, and out-of-service resources",
        ],
        "last_update": datetime.utcnow().isoformat(),
    }


def _score_facility(facility: dict[str, Any], severity: str, preferred: set[str]) -> float:
    status_penalty = {
        "normal": 0,
        "elevated": -16,
        "critical": -35,
        "diversion": -100,
    }.get(facility.get("status", "normal"), 0)
    trauma = facility.get("trauma_level")
    trauma_bonus = 0
    if severity == "critical":
        trauma_bonus = {"I": 22, "II": 16}.get(trauma, 0)
    elif severity == "moderate":
        trauma_bonus = {"I": 10, "II": 8}.get(trauma, 2)
    else:
        trauma_bonus = {"I": 4, "II": 4}.get(trauma, 3)

    distance = facility.get("distance_mi")
    distance_penalty = (distance or 6) * (3 if severity == "critical" else 2)

    beds = facility.get("available_beds")
    bed_bonus = 0
    if beds is not None:
        bed_bonus = min(max(beds, 0), 10)

    preference_penalty = 0
    if facility.get("name") in preferred and severity != "critical":
        preference_penalty = -18 if facility.get("status") in {"elevated", "critical"} else -8
    return 100 + trauma_bonus + bed_bonus + status_penalty + preference_penalty - distance_penalty


def _choose_facility(
    facilities: list[dict[str, Any]],
    severity: str,
    preferred: set[str],
) -> dict[str, Any]:
    scored = sorted(
        (facility for facility in facilities if facility.get("status") != "diversion"),
        key=lambda facility: _score_facility(facility, severity, preferred),
        reverse=True,
    )
    if scored:
        return scored[0]
    return facilities[0]


def _assignment_reason(
    facility: dict[str, Any],
    severity: str,
    primary_route: str,
    *,
    primary_blocked: bool = False,
) -> str:
    trauma = facility.get("trauma_level")
    distance = facility.get("distance_mi")
    parts = []
    if severity == "critical" and trauma:
        parts.append(f"Best trauma match (Trauma {trauma})")
    elif distance is not None:
        parts.append(f"Nearest viable receiving facility at {distance:.1f} mi")
    else:
        parts.append("Best confirmed receiving option")
    if facility.get("status") in {"elevated", "critical"}:
        parts.append(f"Capacity is already {facility['status']}; monitor closely")
    if primary_blocked:
        parts.append("Primary corridor blocked; use alternate transport access")
    else:
        parts.append(f"Uses primary access corridor: {primary_route[:48]}")
    return ". ".join(parts)[:120]


def _reroute_trigger(facility: dict[str, Any]) -> str:
    status = facility.get("status", "normal")
    if status in {"critical", "diversion"}:
        return f"Reroute immediately if {facility['name']} remains {status}"
    return f"Reroute if {facility['name']} reports diversion or access time worsens"


def _allocate_patients(
    counts: dict[str, int],
    facilities: list[dict[str, Any]],
    primary_route: str,
    *,
    primary_blocked: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    assignments: dict[str, dict[str, Any]] = {}
    preferred: set[str] = set()

    def assign_one(severity: str) -> None:
        facility = _choose_facility(facilities, severity, preferred)
        name = facility["name"]
        entry = assignments.setdefault(
            name,
            {
                "hospital": name,
                "patients_assigned": 0,
                "capacity_strain": _status(facility.get("status")),
                "patient_types": [],
                "routing_reason": _assignment_reason(
                    facility,
                    severity,
                    primary_route,
                    primary_blocked=primary_blocked,
                ),
                "reroute_trigger": _reroute_trigger(facility),
            },
        )
        entry["patients_assigned"] += 1
        if severity not in entry["patient_types"]:
            entry["patient_types"].append(severity)
        if entry["capacity_strain"] == "normal" and entry["patients_assigned"] >= 3:
            entry["capacity_strain"] = "elevated"
        if facility.get("available_beds") is not None:
            facility["available_beds"] = max(0, _int(facility.get("available_beds")) - 1)
            if facility["available_beds"] <= 2 and facility.get("status") == "normal":
                facility["status"] = "elevated"
            if facility["available_beds"] == 0:
                facility["status"] = "critical"
        preferred.add(name)

    for severity in ("critical", "moderate", "minor"):
        for _ in range(counts[severity]):
            assign_one(severity)

    ordered = sorted(assignments.values(), key=lambda item: item["patients_assigned"], reverse=True)
    alternates = [facility["name"] for facility in facilities if facility["name"] not in assignments][:2]
    return ordered, alternates


def _triage_priorities(
    counts: dict[str, int],
    assignments: list[dict[str, Any]],
    alternate_route: str,
) -> list[dict[str, Any]]:
    primary = _primary_destination(assignments)
    alternate = _alternate_destination(assignments, primary)
    return [
        {
            "priority": 1,
            "label": "critical",
            "estimated_count": counts["critical"],
            "required_response": "Immediate ALS transport",
            "required_action": f"Stabilize and transport to {primary}",
        },
        {
            "priority": 2,
            "label": "urgent",
            "estimated_count": counts["moderate"],
            "required_response": "Rapid stabilization",
            "required_action": f"Stabilize, then transport to {alternate}",
        },
        {
            "priority": 3,
            "label": "minor",
            "estimated_count": counts["minor"],
            "required_response": "Delayed transport / monitoring",
            "required_action": f"Hold, monitor, and transport if primary access degrades via {alternate_route[:60]}",
        },
    ]


def _risk_state(
    incident_type: str,
    counts: dict[str, int],
    parsed: dict[str, Any],
    ext_ctx: dict[str, Any],
    assignments: list[dict[str, Any]],
    alternates: list[str],
    route_constraints: list[str],
    resource_adequacy: str,
    resource_gaps: list[str],
) -> dict[str, Any]:
    hazards = _safe_list(parsed.get("key_hazards"))
    weather_risk = (((ext_ctx.get("weather") or {}).get("risk")) or {})
    water_risk = (((ext_ctx.get("water") or {}).get("risk")) or {})
    weather_threats = _safe_list(weather_risk.get("weather_threats"))
    weather_triggers = _safe_list(weather_risk.get("escalation_triggers"))
    water_signals = _safe_list(water_risk.get("signals"))
    water_triggers = _safe_list(water_risk.get("replan_triggers"))

    capacity_bottlenecks = [
        f"{assignment['hospital']} is operating at {assignment['capacity_strain']} strain"
        for assignment in assignments
        if assignment["capacity_strain"] in {"elevated", "critical"}
    ]
    transport_delays = route_constraints.copy()
    if not assignments:
        capacity_bottlenecks.append("Receiving hospital assignment is not confirmed")
    if not alternates:
        capacity_bottlenecks.append("No alternate receiving facility is confirmed")

    cascade_risks: list[str] = []
    if assignments and alternates:
        cascade_risks.append(
            f"If {assignments[0]['hospital']} saturates, divert to {alternates[0]} and expect longer turnaround"
        )
    elif assignments:
        cascade_risks.append(
            f"If {assignments[0]['hospital']} loses capacity, destination options become severely constrained"
        )

    immediate_threat = bool(parsed.get("immediate_life_safety_threat"))
    primary_risks = []
    if immediate_threat:
        primary_risks.append("Immediate life safety threat requires critical-patient-first movement")
    if transport_delays:
        primary_risks.append(transport_delays[0])
    if capacity_bottlenecks:
        primary_risks.append(capacity_bottlenecks[0])
    if hazards:
        primary_risks.append(f"Scene hazards affecting care or access: {', '.join(hazards[:2])}")
    if water_signals:
        primary_risks.append(str(water_signals[0]))
    if resource_adequacy != "sufficient":
        primary_risks.append(f"Response resource posture is {resource_adequacy}")

    severity = "medium"
    if immediate_threat or counts["critical"] > 0:
        severity = "high"
    if counts["critical"] >= 2 or any(
        "critical strain" in item.lower() or "unconfirmed" in item.lower() for item in capacity_bottlenecks + transport_delays
    ):
        severity = "critical"
    if water_risk.get("severity") == "high":
        severity = "critical"

    safety = []
    if hazards:
        safety.append(f"Confirm scene safety for {', '.join(hazards[:2])} before full EMS entry")
    safety.append("Keep ingress and egress corridor clear for ambulance movement")
    if immediate_threat:
        safety.append("Prioritize rapid extraction and triage for highest-acuity patients")

    decision_triggers = weather_triggers[:2] + water_triggers[:2]
    decision_triggers.extend([
        "Reroute immediately if primary receiving facility reports diversion",
        "Recompute allocation if critical patient count increases",
    ])

    risk_score = 20
    risk_score += counts["critical"] * 15
    risk_score += len(capacity_bottlenecks) * 10
    risk_score += len(transport_delays) * 8
    risk_score += 10 if immediate_threat else 0
    risk_score += 15 if water_risk.get("severity") == "high" else 6 if water_risk.get("severity") == "moderate" else 0
    risk_score = max(0, min(100, risk_score))

    return {
        "severity_level": severity,
        "confidence": 0.82,
        "risk_score": risk_score,
        "incident_objectives": [
            "Move highest-acuity patients to the best capable receiving facility first",
            "Preserve transport throughput and keep the primary corridor usable",
            "Avoid overloading the nearest receiving hospital",
        ],
        "primary_risks": primary_risks[:4],
        "safety_considerations": safety[:3],
        "weather_driven_threats": list(dict.fromkeys((weather_threats + water_signals)[:3])),
        "replan_triggers": list(dict.fromkeys((decision_triggers + weather_triggers + water_triggers)[:4])),
        "healthcare_risks": capacity_bottlenecks[:3] or ["Receiving capacity remains a live risk until confirmed"],
        "capacity_bottlenecks": capacity_bottlenecks[:3],
        "transport_delays": transport_delays[:3],
        "cascade_risks": cascade_risks[:2],
        "decision_triggers": list(dict.fromkeys(decision_triggers[:4])),
        "resource_adequacy": resource_adequacy,
        "resource_gaps": resource_gaps[:3],
        "estimated_duration_hours": 2.0 if severity != "critical" else 4.0,
        "mutual_aid_needed": resource_adequacy == "insufficient",
    }


def _resource_assignments(resources: list[dict[str, Any]]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = defaultdict(list)
    for resource in resources:
        if not resource.get("available", True):
            continue
        name = resource.get("name") or "Resource"
        role = str(resource.get("role", "")).lower()
        if any(token in role for token in ("ems", "medic", "ambulance")):
            sections["operations"].append(f"{name} -> triage and transport")
        elif any(token in role for token in ("fire", "rescue", "ladder")):
            sections["operations"].append(f"{name} -> scene access and extraction")
        elif "public information" in role or "pio" in role:
            sections["communications"].append(f"{name} -> public messaging")
        elif any(token in role for token in ("eoc", "command", "sheriff", "law")):
            sections["command"].append(f"{name} -> command and corridor control")
        else:
            sections["logistics"].append(f"{name} -> support operations")
    return {
        "operations": sections.get("operations", [])[:4] or ["Assign first-arriving units to rescue and triage"],
        "logistics": sections.get("logistics", [])[:3] or ["Stage transport support and route control equipment"],
        "communications": sections.get("communications", [])[:3] or ["Notify receiving hospitals and keep command updated"],
        "command": sections.get("command", [])[:3] or ["Maintain unified command and confirm reroute triggers"],
    }


def _decision_summary(assignments: list[dict[str, Any]], counts: dict[str, int], incident_type: str) -> str:
    if assignments:
        top = _primary_destination(assignments)
        return (
            f"{incident_type}: route {counts['critical']} critical / {counts['moderate']} moderate / "
            f"{counts['minor']} minor patients with primary receiving focus on {top}."
        )[:220]
    return f"{incident_type}: confirm receiving destinations and move highest-acuity patients first."[:220]


def _state_summary(
    counts: dict[str, int],
    assignments: list[dict[str, Any]],
    risk: dict[str, Any],
    primary_route: str,
) -> str:
    allocation = "; ".join(
        f"{item['hospital']}={item['patients_assigned']} ({'/'.join(item['patient_types'])})"
        for item in assignments[:3]
    ) or "destinations pending"
    risks = "; ".join(risk.get("primary_risks", [])[:3]) or "no major risk identified"
    return (
        f"Patients total={counts['total']} critical={counts['critical']} moderate={counts['moderate']} minor={counts['minor']} | "
        f"Allocation: {allocation} | Route: {primary_route[:90]} | Risks: {risks}"
    )[:520]


def build_decision_state(
    *,
    incident_type: str,
    location: str,
    parsed: dict[str, Any],
    ext_ctx: dict[str, Any],
    resources: list[dict[str, Any]],
    hospital_capacities: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = _count_state(parsed)
    primary_route, alternate_route, route_constraints, route_status = _route_strings(ext_ctx, parsed)
    facilities = _merge_hospitals(ext_ctx, hospital_capacities)
    assignments, alternates = _allocate_patients(
        counts,
        facilities,
        primary_route,
        primary_blocked=bool(route_status.get("primary_blocked")),
    )
    access_constraints = _access_constraints(parsed, route_constraints)
    patient_flow = {
        "total_incoming": counts["total"],
        "critical": counts["critical"],
        "moderate": counts["moderate"],
        "minor": counts["minor"],
        "facility_assignments": assignments,
        "bottlenecks": route_constraints[:],
        "distribution_rationale": (
            "Assignments favor the closest viable trauma-capable hospital for critical patients, "
            "then distribute lower-acuity load to protect receiving capacity."
        )[:180],
    }
    resource_adequacy, resource_gaps = _resource_summary(resources, counts["critical"], counts["total"])
    risk = _risk_state(
        incident_type,
        counts,
        parsed,
        ext_ctx,
        assignments,
        alternates,
        route_constraints,
        resource_adequacy,
        resource_gaps,
    )
    command_structure = _command_structure(
        incident_type,
        counts,
        parsed,
        access_constraints,
        resources,
        assignments,
    )
    objectives = _operational_objectives(counts, assignments, primary_route, risk, command_structure, route_status)
    risk["incident_objectives"] = objectives[:3]
    owned_actions = _owned_actions(
        command_structure,
        counts,
        assignments,
        primary_route,
        alternate_route,
        resource_gaps,
        route_status,
    )
    structured_owned_actions = _structured_owned_actions(
        command_structure,
        counts,
        assignments,
        primary_route,
        alternate_route,
        resource_gaps,
        route_status,
    )
    organization = _ics_organization(command_structure, resources, counts, assignments)
    span_of_control = _span_of_control(command_structure, resources, structured_owned_actions, counts)
    accountability = _accountability_report(structured_owned_actions, command_structure)
    medical_operations = _medical_operations(counts, assignments, alternate_route, route_status)
    assigned_resources, staged_resources, requested_resources, out_of_service_resources = _resource_buckets(resources)

    primary_destination = _primary_destination(assignments)
    alternate_destination = _alternate_destination(assignments, primary_destination)
    patient_transport = {
        "primary_facilities": list(dict.fromkeys(
            [primary_destination] + ([alternate_destination] if alternate_destination and alternate_destination != primary_destination else [])
        ))[:2],
        "alternate_facilities": [item for item in alternates if item != primary_destination][:2],
        "transport_routes": [primary_route, alternate_route],
        "constraints": list(dict.fromkeys((route_constraints + risk.get("capacity_bottlenecks", []))[:4])),
        "fallback_if_primary_unavailable": alternate_route,
    }

    operational_priorities = [
        (
            "Move critical patients first using the alternate transport corridor"
            if route_status.get("primary_blocked")
            else "Move critical patients first using the primary access corridor"
        ),
        "Protect receiving capacity by splitting lower-acuity load",
        "Keep reroute triggers active for route or hospital status changes",
    ]

    return {
        "incident_type": incident_type,
        "location": location,
        "counts": counts,
        "hazards": _safe_list(parsed.get("key_hazards"))[:4],
        "access_constraints": access_constraints,
        "route_evaluation": {
            "provider": (((ext_ctx.get("mapping") or {}).get("routing")) or {}).get("provider", "unknown"),
            "primary_route": primary_route,
            "alternate_route": alternate_route,
            "constraints": route_constraints,
            "primary_duration_min": (((ext_ctx.get("mapping") or {}).get("routing")) or {}).get("primary_duration_min"),
            "alternate_confirmed": route_status.get("alternate_confirmed", False),
            "primary_blocked": route_status.get("primary_blocked", False),
        },
        "patient_flow": patient_flow,
        "triage_priorities": _triage_priorities(counts, assignments, alternate_route),
        "patient_transport": patient_transport,
        "primary_access_route": primary_route,
        "alternate_access_route": alternate_route,
        "risk": risk,
        "operational_priorities": operational_priorities,
        "operational_objectives": objectives,
        "resource_assignments": _resource_assignments(resources),
        "assigned_resources": assigned_resources,
        "staged_resources": staged_resources,
        "requested_resources": requested_resources,
        "out_of_service_resources": out_of_service_resources,
        "command_recommendations": command_structure,
        "owned_actions": owned_actions,
        "owned_action_items": structured_owned_actions,
        "ics_organization": organization,
        "span_of_control": span_of_control,
        "accountability": accountability,
        "medical_operations": medical_operations,
        "command_transfer_summary": _command_transfer_summary(
            command_structure,
            objectives,
            _safe_list(parsed.get("key_hazards")),
            owned_actions,
            risk,
            resources,
        ),
        "iap": _incident_action_plan(
            command_structure,
            organization,
            objectives,
            structured_owned_actions,
            risk,
            str(parsed.get("operational_period") or ""),
        ),
        "transport_group_active": command_structure.get("transport_group_active", False),
        "assumptions": [
            {
                "description": (
                    "Alternate transport corridor remains usable for EMS transport"
                    if route_status.get("primary_blocked")
                    else "Primary access corridor remains usable for EMS transport"
                ),
                "impact": (
                    "If false, hold transport, confirm alternate access, and reallocate patients"
                    if route_status.get("primary_blocked")
                    else "If false, switch to alternate route and reallocate patients"
                ),
                "confidence": 0.5,
            },
            {
                "description": "Receiving hospitals maintain current posted capacity status",
                "impact": "If false, divert to alternates and rebalance load",
                "confidence": 0.5,
            },
        ],
        "missing_information": (parsed.get("unknowns") or ["Confirm exact patient acuity and route status"])[:4],
        "decision_summary": _decision_summary(assignments, counts, incident_type),
        "computed_state_summary": _state_summary(counts, assignments, risk, primary_route),
    }


def validate_decision_state(decision_state: dict[str, Any]) -> None:
    patient_flow = decision_state.get("patient_flow") or {}
    assignments = _safe_list(patient_flow.get("facility_assignments"))
    total = _int(patient_flow.get("total_incoming"))
    assigned_total = sum(_int(item.get("patients_assigned")) for item in assignments if isinstance(item, dict))
    if total != assigned_total:
        raise ValueError(
            f"Decision engine allocation mismatch: total_incoming={total}, assigned_total={assigned_total}"
        )
    command_recommendations = decision_state.get("command_recommendations") or {}
    command_mode = str(command_recommendations.get("command_mode", "")).strip().lower()
    if command_mode not in {"investigative", "fast_attack", "command"}:
        raise ValueError(f"Decision engine command mode is invalid: {command_mode or 'missing'}")
    accountability = decision_state.get("accountability") or {}
    if _safe_list(accountability.get("unowned_actions")):
        raise ValueError("Decision engine produced unowned critical actions")
    owned_action_items = _safe_list(decision_state.get("owned_action_items"))
    if not owned_action_items:
        raise ValueError("Decision engine produced no structured owned actions")
    for action in owned_action_items:
        if not isinstance(action, dict):
            continue
        if not str(action.get("owner_role") or "").strip():
            raise ValueError("Decision engine produced an action without an owner_role")
    medical_operations = decision_state.get("medical_operations") or {}
    for branch_name in ("triage", "treatment", "transport"):
        branch = medical_operations.get(branch_name) or {}
        if not str(branch.get("owner_role") or "").strip():
            raise ValueError(f"Decision engine medical branch '{branch_name}' is missing an owner_role")
