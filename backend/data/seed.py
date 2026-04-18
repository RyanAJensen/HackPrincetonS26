"""
Seeded multi-agency resources and medically-focused demo incident scenarios.
Each scenario exercises medical triage, EMS coordination, and hospital routing:
  - Flash Flood: trapped patients, delayed EMS access, hospital transport planning
  - Hazmat Exposure: respiratory casualties, decontamination triage, capacity strain
  - Severe Storm: multiple trauma injuries, blocked routes, critical patient evacuation
"""
from models.incident import Resource, IncidentCreate, SeverityLevel

CAMPUS_RESOURCES: list[Resource] = [
    Resource(name="EMS Unit 12", role="Emergency Medical Services", location="EMS Station 2", contact="911"),
    Resource(name="EMS Unit 15", role="Emergency Medical Services", location="EMS Station 4", contact="911"),
    Resource(name="EMS Unit 8 — Advanced Life Support", role="Emergency Medical Services / ALS", location="EMS Station 1", contact="911"),
    Resource(name="Engine Co. 7", role="Fire / Rescue", location="Station 7 — Main St", contact="911"),
    Resource(name="Ladder Co. 3", role="Fire / Rescue", location="Station 3 — Central Ave", contact="911"),
    Resource(name="HAZMAT Team Alpha", role="Hazardous Materials", location="County HAZMAT Depot", contact="911"),
    Resource(name="County Sheriff — Patrol Division", role="Law Enforcement", contact="911"),
    Resource(name="Emergency Operations Center", role="Command & Coordination", location="EOC — Government Center", contact="555-0100"),
    Resource(name="Public Works — Emergency Crew", role="Infrastructure / Roads", contact="555-0200"),
    Resource(name="Penn Medicine Princeton Medical Center", role="Medical / Trauma Receiving", location="One Plainsboro Rd, Plainsboro NJ", contact="555-0300"),
    Resource(name="Regional Trauma Coordinator", role="Hospital Coordination", location="Regional Medical Center", contact="555-0301"),
    Resource(name="Public Information Officer", role="Communications / Media", contact="555-0400"),
]

DEMO_SCENARIOS: list[dict] = [
    {
        "id": "demo-flood",
        "label": "Flash Flood with Injuries",
        "sub": "Stranded vehicles, injured civilians, delayed EMS access — Washington Road corridor",
        "incident": IncidentCreate(
            incident_type="Flash Flood / Mass Casualty",
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
                "Nearest hospital with trauma capability is Penn Medicine Princeton Medical Center, approx 4 miles east."
            ),
            location="Washington Road at Lake Carnegie Bridge, Princeton, NJ",
            severity_hint=SeverityLevel.CRITICAL,
            resources=CAMPUS_RESOURCES,
        ),
    },
    {
        "id": "demo-hazmat",
        "label": "Hazmat Exposure Event",
        "sub": "Respiratory distress risk, decontamination and hospital coordination",
        "incident": IncidentCreate(
            incident_type="Hazardous Materials Exposure / Mass Casualty",
            report=(
                "At 2:14 PM, a pressurized cylinder of chlorine gas ruptured in a ground-floor laboratory "
                "at a research facility on Nassau Street. Twelve personnel were present in the immediate area. "
                "Three occupants have collapsed with severe respiratory distress and are unable to self-evacuate; "
                "one is unconscious. Five additional personnel have evacuated but report burning eyes, "
                "throat irritation, and difficulty breathing. Four personnel are unaccounted for. "
                "The building has not been fully evacuated. Ventilation systems are running, potentially "
                "distributing contaminated air to adjacent floors. An estimated 200 additional personnel "
                "are in neighboring buildings within the plume zone. Wind is currently 8 mph from the west. "
                "No decontamination corridor has been established. Nearest decontamination-capable facility "
                "is Capital Health Regional Medical Center in Trenton, 13 miles south. "
                "Penn Medicine Princeton Medical Center is 4 miles east but has limited decon capacity."
            ),
            location="Nassau Street Research Facility, Princeton, NJ",
            severity_hint=SeverityLevel.CRITICAL,
            resources=CAMPUS_RESOURCES,
        ),
    },
    {
        "id": "demo-storm",
        "label": "Severe Storm with Multiple Casualties",
        "sub": "Structural damage, multiple injury severities, transport route disruption",
        "incident": IncidentCreate(
            incident_type="Severe Weather / Mass Casualty Incident",
            report=(
                "A fast-moving severe thunderstorm cell crossed the area at 4:45 PM with sustained "
                "winds of 62 mph and gusts recorded at 78 mph. A partial roof collapse has occurred "
                "at the Princeton Community Center on Witherspoon Street — approximately 40 people were "
                "inside during the event. Current confirmed injuries: 2 patients with crush injuries "
                "(one with suspected spinal trauma), 3 patients with lacerations requiring suturing, "
                "2 patients with suspected fractures, and at least 1 patient in respiratory distress "
                "from dust inhalation. Approximately 12 additional individuals have minor injuries. "
                "A large tree has fallen across Witherspoon Street and Nassau Street — both primary "
                "EMS corridors to Penn Medicine Princeton Medical Center are blocked. "
                "The alternate route via Route 1 adds 18 minutes to transport time. "
                "Power is out across 6 blocks. Emergency generators at the community center have not activated. "
                "A second storm cell is approaching from the southwest, estimated arrival in 22 minutes."
            ),
            location="Princeton Community Center, Witherspoon Street, Princeton, NJ",
            severity_hint=SeverityLevel.CRITICAL,
            resources=CAMPUS_RESOURCES,
        ),
    },
]
