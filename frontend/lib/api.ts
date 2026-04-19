function defaultApiBase() {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window === "undefined" && process.env.INTERNAL_API_URL) {
    return process.env.INTERNAL_API_URL;
  }
  if (typeof window !== "undefined") {
    const host = window.location.hostname || "localhost";
    return `http://${host}:8000/api/v1`;
  }
  return "http://localhost:8000/api/v1";
}

function networkFailureMessage(url: string, err: unknown) {
  const detail = err instanceof Error ? err.message : String(err);
  return (
    `Unable to reach the Unilert backend at ${url}. ` +
    `Make sure the FastAPI server is running on port 8000 and that NEXT_PUBLIC_API_URL points to the correct backend. ` +
    `If you opened the frontend on a network hostname or IP, the backend must be reachable from that same host. ` +
    `Original error: ${detail}`
  );
}

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const url = `${defaultApiBase()}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
  } catch (err) {
    throw new Error(networkFailureMessage(url, err));
  }
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

// --- Types (mirrors backend Pydantic models) ---

export interface HospitalCapacity {
  name: string;
  available_beds?: number | null;
  total_beds?: number | null;
  status: string;
  specialty?: string | null;
  distance_mi?: number | null;
  eta_min?: number | null;
}

export interface FacilityAssignment {
  hospital: string;
  patients_assigned: number;
  capacity_strain: "normal" | "elevated" | "critical";
  patient_types: string[];
  routing_reason: string;
  reroute_trigger: string;
}

export interface PatientFlowSummary {
  total_incoming: number;
  critical: number;
  moderate: number;
  minor: number;
  facility_assignments: FacilityAssignment[];
  bottlenecks: string[];
  distribution_rationale: string;
}

export interface DecisionPoint {
  decision: string;
  reason: string;
  assumption: string;
  replan_trigger: string;
}

export interface Tradeoff {
  description: string;
  option_a: string;
  option_b: string;
  recommendation: string;
}

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
  required_response?: string;
  required_action: string;
}

export interface PatientTransport {
  primary_facilities: string[];
  alternate_facilities: string[];
  transport_routes: string[];
  constraints: string[];
  fallback_if_primary_unavailable?: string;
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
  deployment_status?: string;
  ics_group?: string | null;
  location?: string;
  contact?: string;
}

export interface IncidentLogEntry {
  timestamp: string;
  source: string;
  category: string;
  message: string;
}

export interface CommandRecommendations {
  command_mode: string;
  command_post_established: boolean;
  unified_command_recommended: boolean;
  safety_officer_recommended: boolean;
  public_information_officer_recommended?: boolean;
  liaison_officer_recommended?: boolean;
  operations_section_active?: boolean;
  planning_section_active?: boolean;
  logistics_section_active?: boolean;
  finance_admin_section_active?: boolean;
  triage_group_active?: boolean;
  treatment_group_active?: boolean;
  staging_area: string;
  transport_group_active: boolean;
  rationale: string[];
}

export interface CommandTransferSummary {
  command_mode: string;
  current_strategy: string;
  active_groups: string[];
  top_hazards: string[];
  next_decisions: string[];
  resource_status?: string[];
  transfer_needs?: string[];
  last_update: string;
}

export interface ICSRoleAssignment {
  role: string;
  assigned_to?: string | null;
  agency?: string | null;
  active: boolean;
  responsibilities: string[];
}

export interface OwnedOperationalAction {
  description: string;
  owner_role: string;
  owner_name?: string | null;
  operational_group?: string | null;
  timeframe?: string | null;
  priority: number;
  contingency?: string | null;
  critical: boolean;
}

export interface SpanOfControlWarning {
  supervisor_role: string;
  direct_reports: number;
  recommended_structure: string;
  reason: string;
  severity: string;
}

export interface AccountabilityIssue {
  kind: string;
  severity: string;
  message: string;
  action_description?: string | null;
  owner_role?: string | null;
}

export interface AccountabilityReport {
  status: string;
  unowned_actions: string[];
  conflicting_assignments: string[];
  duplicate_assignments: string[];
  self_dispatch_risks: string[];
  issues: AccountabilityIssue[];
}

export interface MedicalOperationsBranch {
  group_name: string;
  owner_role: string;
  objectives: string[];
  actions: OwnedOperationalAction[];
  status: string;
}

export interface MedicalOperationsSummary {
  triage: MedicalOperationsBranch;
  treatment: MedicalOperationsBranch;
  transport: MedicalOperationsBranch;
}

export interface IncidentActionPlan {
  command_intent: string;
  current_objectives: string[];
  organization: ICSRoleAssignment[];
  owned_actions: OwnedOperationalAction[];
  communications_plan: string[];
  responder_injury_contingency: string[];
  degradation_triggers: string[];
  operational_period: string;
}

export interface FallbackSummary {
  mode_active: boolean;
  safe_to_act_on: string[];
  unavailable_components: string[];
  unverified_assumptions: string[];
}

export interface Incident {
  id: string;
  created_at: string;
  updated_at: string;
  incident_type: string;
  report: string;
  location: string;
  severity_hint?: SeverityLevel;
  hazards?: string[];
  access_constraints?: string[];
  estimated_patients?: number;
  triage_counts?: { critical: number; moderate: number; minor: number };
  command_mode?: string | null;
  command_post_established?: boolean;
  unified_command?: boolean;
  safety_officer_assigned?: boolean;
  staging_area?: string | null;
  operational_objectives?: string[];
  resources: Resource[];
  ics_organization?: ICSRoleAssignment[];
  assigned_resources?: string[];
  staged_resources?: string[];
  requested_resources?: string[];
  out_of_service_resources?: string[];
  transport_group_active?: boolean;
  current_bottlenecks?: string[];
  incident_log?: IncidentLogEntry[];
  hospital_capacities: HospitalCapacity[];
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

  // Patient flow & facility routing decisions
  patient_flow?: PatientFlowSummary | null;
  decision_points: DecisionPoint[];
  command_recommendations?: CommandRecommendations | null;
  owned_actions?: Record<string, string[]>;
  owned_action_items?: OwnedOperationalAction[];
  ics_organization?: ICSRoleAssignment[];
  span_of_control?: SpanOfControlWarning[];
  accountability?: AccountabilityReport | null;
  medical_operations?: MedicalOperationsSummary | null;
  iap?: IncidentActionPlan | null;
  command_transfer_summary?: CommandTransferSummary | null;
  tradeoffs: Tradeoff[];

  // Legacy triage (kept for compat)
  medical_impact?: MedicalImpact | null;
  triage_priorities: TriagePriority[];
  patient_transport?: PatientTransport | null;

  diff_summary?: string;
  changed_sections?: string[];
  first_response_ready?: boolean;
  enrichment_pending?: boolean;
  fallback_mode?: boolean;
  recommendation_confidence?: number;
  route_confidence?: string;
  unavailable_components?: string[];
  verified_information?: string[];
  assumed_information?: string[];
  fallback_summary?: FallbackSummary | null;
  incident_log?: IncidentLogEntry[];
  external_context?: {
    geocoded?: boolean;
    coordinates?: { lat: number; lon: number };
    display_address?: string;
    weather_alerts?: { event: string; severity: string; headline: string }[];
    alert_count?: number;
    forecast?: { temperature_f?: number; short_forecast?: string; wind_speed?: string } | null;
    weather_risk?: string;
    routing?: { duration_min?: number; distance_mi?: number; steps?: string[]; origin?: string; provider?: string; alternate_steps?: string[] } | null;
    fema_context?: string[];
    weather_driven_threats?: string[];
    replan_triggers?: string[];
    water_context?: {
      nearest_gage?: string | null;
      distance_mi?: number | null;
      gage_height_ft?: number | null;
      streamflow_cfs?: number | null;
      water_risk?: string;
      signals?: string[];
    } | null;
    primary_access_route?: string | null;
    alternate_access_route?: string | null;
    healthcare_risks?: string[];
    hospitals?: { name: string; distance_mi?: number | null; trauma_level?: string | null; facility_type?: string | null; capabilities?: string[] }[];
    hospital_directory_source?: string;
    routing_provider?: string;
    dedalus_execution?: string;
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
  error_kind?: string;
  retry_count?: number;
  latency_ms?: number;
  required?: boolean;
  degraded?: boolean;
  fallback_used?: boolean;
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

export interface LiveIncidentResponse {
  incident: Incident;
  plan?: PlanVersion | null;
  agent_runs: AgentRun[];
}

// --- API calls ---

export const api = {
  incidents: {
    list: () => req<Incident[]>("/incidents"),
    get: (id: string) => req<Incident>(`/incidents/${id}`),
    live: (id: string) => req<LiveIncidentResponse>(`/incidents/${id}/live`),
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
