"""
Healthcare surge coordination demo scenarios for Unilert.
Each scenario exercises patient flow decisions, facility routing, and capacity coordination.
"""
from models.incident import Resource, IncidentCreate, HospitalCapacity, SeverityLevel

REGIONAL_RESOURCES: list[Resource] = [
    Resource(name="EMS Unit 12", role="Emergency Medical Services", location="EMS Station 2", contact="911"),
    Resource(name="EMS Unit 15", role="Emergency Medical Services", location="EMS Station 4", contact="911"),
    Resource(name="EMS Unit 8 — Advanced Life Support", role="Emergency Medical Services / ALS", location="EMS Station 1", contact="911"),
    Resource(name="Engine Co. 7", role="Fire / Rescue", location="Station 7 — Main St", contact="911"),
    Resource(name="HAZMAT Team Alpha", role="Hazardous Materials", location="County HAZMAT Depot", contact="911"),
    Resource(name="County Sheriff — Patrol Division", role="Law Enforcement", contact="911"),
    Resource(name="Emergency Operations Center", role="Command & Coordination", location="EOC — Government Center", contact="555-0100"),
    Resource(name="Regional Trauma Coordinator", role="Hospital Coordination", contact="555-0301"),
    Resource(name="Public Information Officer", role="Communications / Media", contact="555-0400"),
]

FLOOD_HOSPITALS: list[HospitalCapacity] = [
    HospitalCapacity(name="Penn Medicine Princeton Medical Center", available_beds=8, total_beds=42, status="elevated", specialty="trauma", distance_mi=4.2, eta_min=12),
    HospitalCapacity(name="Capital Health Regional — Trenton", available_beds=22, total_beds=80, status="normal", specialty="trauma", distance_mi=13.5, eta_min=28),
    HospitalCapacity(name="Robert Wood Johnson University Hospital", available_beds=5, total_beds=35, status="critical", specialty="trauma", distance_mi=9.1, eta_min=22),
]

HAZMAT_HOSPITALS: list[HospitalCapacity] = [
    HospitalCapacity(name="Capital Health Regional — Trenton", available_beds=18, total_beds=80, status="normal", specialty="decon", distance_mi=13.5, eta_min=25),
    HospitalCapacity(name="Penn Medicine Princeton Medical Center", available_beds=6, total_beds=42, status="elevated", specialty="general", distance_mi=4.2, eta_min=10),
    HospitalCapacity(name="University Medical Center of Princeton", available_beds=3, total_beds=28, status="critical", distance_mi=5.0, eta_min=13),
]

STORM_HOSPITALS: list[HospitalCapacity] = [
    HospitalCapacity(name="Penn Medicine Princeton Medical Center", available_beds=4, total_beds=42, status="critical", specialty="trauma", distance_mi=1.8, eta_min=20),
    HospitalCapacity(name="Capital Health Regional — Trenton", available_beds=24, total_beds=80, status="normal", specialty="trauma", distance_mi=13.5, eta_min=38),
    HospitalCapacity(name="Robert Wood Johnson University Hospital", available_beds=11, total_beds=35, status="elevated", specialty="trauma", distance_mi=9.1, eta_min=28),
]

DEMO_SCENARIOS: list[dict] = [
    {
        "id": "demo-flood",
        "label": "Flash Flood with Injuries",
        "sub": "Stranded vehicles, injured civilians, delayed EMS access, Washington Road corridor",
        "incident": IncidentCreate(
            incident_type="Flash Flood with Injuries / Access Limited",
            report=(
                "Heavy rainfall over the past 90 minutes has caused Washington Road to flood at the "
                "Lake Carnegie bridge crossing. Water depth is estimated at 18-24 inches and rising rapidly. "
                "Four individuals are trapped in two stalled vehicles — one is an elderly female (approx 70s) "
                "who is unresponsive; a second occupant has visible head trauma from the collision. "
                "Two additional people are ambulatory but stranded on the vehicle roofs. "
                "A bystander reports the elderly patient may be in cardiac arrest. "
                "Washington Road is the primary EMS corridor to the south side of the jurisdiction — "
                "current flooding has made it impassable to standard ambulances. "
                "A second water surge is anticipated within 20 minutes as upstream retention basins approach capacity. "
                "Penn Medicine Princeton Medical Center has radioed that their trauma bay is nearly full — "
                "only 8 beds remain and they have 2 incoming critical patients from an earlier MVA. "
                "Capital Health in Trenton has capacity but is 13 miles south."
            ),
            location="Washington Road at Lake Carnegie Bridge, Princeton, NJ",
            severity_hint=SeverityLevel.CRITICAL,
            resources=REGIONAL_RESOURCES,
            hospital_capacities=FLOOD_HOSPITALS,
        ),
    },
    {
        "id": "demo-hazmat",
        "label": "Hazmat Exposure Event",
        "sub": "Respiratory distress risk, decontamination and hospital coordination",
        "incident": IncidentCreate(
            incident_type="Hazmat Exposure / Respiratory Casualties",
            report=(
                "At 2:14 PM, a pressurized cylinder of chlorine gas ruptured in a ground-floor laboratory "
                "at a research facility on Nassau Street. Twelve personnel were present in the immediate area. "
                "Three occupants have collapsed with severe respiratory distress and are unable to self-evacuate; "
                "one is unconscious. Five additional personnel have evacuated but report burning eyes, "
                "throat irritation, and difficulty breathing. Four personnel are unaccounted for. "
                "The building has not been fully evacuated. Ventilation systems are running, potentially "
                "distributing contaminated air to adjacent floors. An estimated 200 additional personnel "
                "are in neighboring buildings within the plume zone. Wind is currently 8 mph from the west. "
                "No decontamination corridor has been established. Capital Health in Trenton is the only "
                "regional facility with full decon capability. Penn Medicine has limited decon capacity "
                "and is currently at elevated status from earlier admissions."
            ),
            location="Nassau Street Research Facility, Princeton, NJ",
            severity_hint=SeverityLevel.CRITICAL,
            resources=REGIONAL_RESOURCES,
            hospital_capacities=HAZMAT_HOSPITALS,
        ),
    },
    {
        "id": "demo-storm",
        "label": "Severe Storm with Multiple Casualties",
        "sub": "Structural damage, mixed injury severities, transport route disruption",
        "incident": IncidentCreate(
            incident_type="Severe Storm / Multiple Trauma Casualties",
            report=(
                "A fast-moving severe thunderstorm cell crossed the area at 4:45 PM with sustained "
                "winds of 62 mph. A partial roof collapse occurred at the Princeton Community Center on "
                "Witherspoon Street — approximately 40 people were inside. Confirmed injuries: "
                "2 patients with crush injuries (one with suspected spinal trauma), 3 with lacerations "
                "requiring suturing, 2 with suspected fractures, 1 in respiratory distress from dust inhalation. "
                "Approximately 12 additional individuals have minor injuries. "
                "A large tree has fallen across Witherspoon Street — the primary EMS route to Penn Medicine "
                "Princeton Medical Center is blocked. Penn Medicine is reporting critical capacity: "
                "only 4 trauma beds available and their ED is on diversion advisory. "
                "The alternate route via Route 1 to Capital Health adds 18 minutes. "
                "Robert Wood Johnson in New Brunswick has 11 beds at elevated status. "
                "Power is out across 6 blocks. A second storm cell arrives in 22 minutes."
            ),
            location="Princeton Community Center, Witherspoon Street, Princeton, NJ",
            severity_hint=SeverityLevel.CRITICAL,
            resources=REGIONAL_RESOURCES,
            hospital_capacities=STORM_HOSPITALS,
        ),
    },
]
