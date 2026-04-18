const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

// --- Types (mirrors backend Pydantic models) ---

export interface MedicalImpact {
  affected_population: string;
  estimated_injured: string;
  critical: number;
  moderate: number;
  minor: number;
  at_risk_groups: string[];
}

export interface TriagePriority {
  priority: number;
  label: string;
  estimated_count: number;
  required_action: string;
}

export interface PatientTransport {
  primary_facilities: string[];
  alternate_facilities: string[];
  transport_routes: string[];
  constraints: string[];
}

export type SeverityLevel = "low" | "medium" | "high" | "critical";
export type IncidentStatus = "pending" | "analyzing" | "active" | "replanning" | "resolved";
export type AgentStatus = "pending" | "running" | "completed" | "failed";
export type AgentType = "incident_parser" | "risk_assessor" | "action_planner" | "communications";

export interface Resource {
  id: string;
  name: string;
  role: string;
  available: boolean;
  location?: string;
  contact?: string;
}

export interface Incident {
  id: string;
  created_at: string;
  updated_at: string;
  incident_type: string;
  report: string;
  location: string;
  severity_hint?: SeverityLevel;
  resources: Resource[];
  status: IncidentStatus;
  current_plan_version: number;
}

export interface ActionItem {
  id: string;
  description: string;
  assigned_to?: string;
  timeframe?: string;
  priority: number;
}

export interface RoleAssignment {
  role: string;
  assigned_to: string;
  responsibilities: string[];
}

export interface CommunicationDraft {
  id: string;
  audience: string;
  channel: string;
  subject?: string;
  body: string;
  urgency: string;
}

export interface Assumption {
  id: string;
  description: string;
  impact: string;
  confidence: number;
}

export interface PlanVersion {
  id: string;
  incident_id: string;
  version: number;
  created_at: string;
  trigger: string;

  // IAP Section 1 — Incident Overview
  incident_summary: string;
  operational_period: string;

  // IAP Section 2 — Incident Objectives
  incident_objectives: string[];

  // IAP Section 3 — Operational Priorities
  operational_priorities: string[];

  // IAP Section 4 — Execution Plan
  immediate_actions: ActionItem[];    // 0–10 min
  short_term_actions: ActionItem[];   // 10–30 min
  ongoing_actions: ActionItem[];      // 30–120 min

  // IAP Section 5 — Resource Assignments
  resource_assignments?: {
    operations?: string[];
    logistics?: string[];
    communications?: string[];
    command?: string[];
  };
  role_assignments: RoleAssignment[];

  // IAP Section 6 — Safety
  safety_considerations: string[];

  // IAP Section 7 — Communications
  communications: CommunicationDraft[];

  // IAP Section 8 — Situation Status
  confirmed_facts: string[];
  unknowns: string[];
  assumptions: Assumption[];
  missing_information: string[];

  // Meta
  assessed_severity: string;
  confidence_score: number;
  risk_notes: string[];

  // IAP Section 9 — Medical Triage
  medical_impact?: MedicalImpact | null;
  triage_priorities: TriagePriority[];
  patient_transport?: PatientTransport | null;

  diff_summary?: string;
  changed_sections?: string[];
  external_context?: {
    geocoded?: boolean;
    coordinates?: { lat: number; lon: number };
    display_address?: string;
    weather_alerts?: { event: string; severity: string; headline: string }[];
    alert_count?: number;
    forecast?: { temperature_f?: number; short_forecast?: string; wind_speed?: string } | null;
    weather_risk?: string;
    routing?: { duration_min?: number; distance_mi?: number; steps?: string[]; origin?: string } | null;
    fema_context?: string[];
    weather_driven_threats?: string[];
    replan_triggers?: string[];
    primary_access_route?: string | null;
    alternate_access_route?: string | null;
    healthcare_risks?: string[];
    hospitals?: { name: string; distance_mi?: number | null; trauma_level?: string | null }[];
  };
}

export interface PlanDiff {
  from_version: number;
  to_version: number;
  summary: string;
  changed_sections: string[];
  added_actions: ActionItem[];
  removed_actions: ActionItem[];
  modified_actions: unknown[];
  updated_priorities?: string[];
  updated_role_assignments?: RoleAssignment[];
}

export interface AgentRun {
  id: string;
  incident_id: string;
  plan_version: number;
  agent_type: AgentType;
  status: AgentStatus;
  started_at?: string;
  completed_at?: string;
  runtime: string;
  machine_id?: string;
  output_artifact?: Record<string, unknown>;
  error_message?: string;
  log_entries: string[];
}

export interface AnalysisResponse {
  incident: Incident;
  plan: PlanVersion;
  agent_runs: AgentRun[];
}

export interface ReplanResponse {
  incident: Incident;
  plan: PlanVersion;
  diff: PlanDiff;
  agent_runs: AgentRun[];
}

// --- API calls ---

export const api = {
  incidents: {
    list: () => req<Incident[]>("/incidents"),
    get: (id: string) => req<Incident>(`/incidents/${id}`),
    create: (body: { incident_type: string; report: string; location: string; severity_hint?: string; resources?: Resource[] }) =>
      req<Incident>("/incidents", { method: "POST", body: JSON.stringify(body) }),
    analyze: (id: string) => req<AnalysisResponse>(`/incidents/${id}/analyze`, { method: "POST" }),
    replan: (id: string, update_text: string) =>
      req<ReplanResponse>(`/incidents/${id}/replan`, { method: "POST", body: JSON.stringify({ update_text }) }),
  },
  plans: {
    list: (incidentId: string) => req<PlanVersion[]>(`/incidents/${incidentId}/plans`),
    get: (incidentId: string, version: number) => req<PlanVersion>(`/incidents/${incidentId}/plans/${version}`),
    diff: (incidentId: string, v1: number, v2: number) =>
      req<PlanDiff>(`/incidents/${incidentId}/plans/${v1}/diff/${v2}`),
  },
  agentRuns: {
    list: (incidentId: string, planVersion?: number) =>
      req<AgentRun[]>(`/incidents/${incidentId}/agent-runs${planVersion !== undefined ? `?plan_version=${planVersion}` : ""}`),
  },
  demo: {
    scenarios: () => req<{ id: string; label: string }[]>("/demo/scenarios"),
    load: (scenarioId: string) => req<Incident>(`/demo/scenarios/${scenarioId}/load`, { method: "POST" }),
    resources: () => req<Resource[]>("/demo/resources"),
  },
};
