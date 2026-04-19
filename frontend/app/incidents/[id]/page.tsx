"use client";
import { useState, useEffect, use, useRef, useEffectEvent } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { SeverityBadge } from "@/components/sentinel/SeverityBadge";
import { PriorityActions } from "@/components/sentinel/PriorityActions";
import { SystemActivity } from "@/components/sentinel/SystemActivity";
import { Accordion } from "@/components/sentinel/Accordion";
import { CommunicationsPanel } from "@/components/sentinel/CommunicationsPanel";
import { PlanVersionHistory } from "@/components/sentinel/PlanVersionHistory";
import { ExternalContextPanel } from "@/components/sentinel/ExternalContextPanel";
import { api, type Incident, type PlanVersion, type AgentRun, type PlanDiff, type ActionItem, type MedicalImpact, type TriagePriority, type PatientTransport, type PatientFlowSummary, type FacilityAssignment, type DecisionPoint, type Tradeoff, type AgentType, type CommandRecommendations, type CommandTransferSummary, type IncidentLogEntry } from "@/lib/api";

const QUICK_UPDATES = [
  "Additional patients found — revise counts",
  "Primary route blocked — need alternate",
  "Receiving hospital at capacity — reroute",
  "Critical patient deteriorating — transport now",
  "Decon corridor established — update routing",
  "Hospital confirmed ready — update ETA",
];

const UNIT_LABELS: Record<string, string> = {
  incident_parser: "Situation Unit",
  risk_assessor: "Threat Analysis",
  action_planner: "Operations Planner",
  communications: "Communications Officer",
};

const BOTTLENECK_TONES = {
  critical: {
    badge: "border-red-500/30 bg-red-500/10 text-red-300",
    bar: "bg-red-400",
  },
  elevated: {
    badge: "border-orange-500/30 bg-orange-500/10 text-orange-300",
    bar: "bg-orange-400",
  },
  watch: {
    badge: "border-yellow-500/25 bg-yellow-500/8 text-yellow-200",
    bar: "bg-yellow-400",
  },
};

function stripOrdering(text?: string) {
  return (text ?? "").replace(/^\d+\.\s*/, "").trim();
}

function compactText(text?: string, max = 120) {
  const cleaned = (text ?? "").replace(/\s+/g, " ").trim();
  if (!cleaned) return "";
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max - 1).trimEnd()}…`;
}

function firstSentence(text?: string, max = 140) {
  const cleaned = (text ?? "").replace(/\s+/g, " ").trim();
  if (!cleaned) return "";
  const sentence = cleaned.split(/(?<=[.!?])\s+/)[0] ?? cleaned;
  return compactText(sentence, max);
}

function uniqueStrings(values: (string | undefined | null)[]) {
  return [...new Set(values.map((value) => (value ?? "").trim()).filter(Boolean))];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown) {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown, fallback = 0) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function asBoolean(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function asStringArray(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => (typeof item === "string" ? item.trim() : "")).filter(Boolean)
    : [];
}

function normalizeName(value?: string | null) {
  return (value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function latestRunByType(runs: AgentRun[], agentType: AgentType) {
  return [...runs].reverse().find((run) => run.agent_type === agentType);
}

function runHasUsableOutput(run?: AgentRun | null) {
  return Boolean(run && run.output_artifact && Object.keys(run.output_artifact).length > 0);
}

function runIsActuallyUnavailable(run?: AgentRun | null) {
  if (!run || run.status !== "failed") return false;
  if (run.fallback_used && runHasUsableOutput(run)) return false;
  return !runHasUsableOutput(run);
}

function parseDraftActions(
  value: unknown,
  fallbackAssignedTo: string,
  fallbackTimeframe: string,
): ActionItem[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (typeof item === "string") {
      return [{
        id: `draft-action-${index}-${item}`,
        description: item,
        assigned_to: fallbackAssignedTo,
        timeframe: fallbackTimeframe,
        priority: index + 1,
      }];
    }
    const record = asRecord(item);
    if (!record) return [];
    const description = asString(record.description);
    if (!description) return [];
    return [{
      id: `draft-action-${index}-${description}`,
      description,
      assigned_to: asString(record.assigned_to) || fallbackAssignedTo,
      timeframe: asString(record.timeframe) || fallbackTimeframe,
      priority: index + 1,
    }];
  });
}

function parseDraftAssumptions(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (typeof item === "string") {
      return [{
        id: `draft-assumption-${index}`,
        description: item,
        impact: "Monitor and verify",
        confidence: 0.5,
      }];
    }
    const record = asRecord(item);
    if (!record) return [];
    const description = asString(record.description);
    if (!description) return [];
    return [{
      id: `draft-assumption-${index}`,
      description,
      impact: asString(record.impact) || "Monitor and verify",
      confidence: typeof record.confidence === "number" ? record.confidence : 0.5,
    }];
  });
}

function parseDraftCommunications(value: unknown) {
  const record = asRecord(value);
  if (!record) return [] as PlanVersion["communications"];
  const entries = [
    { key: "ems_brief", audience: "EMS dispatch", channel: "radio", subject: undefined, urgency: "immediate" },
    { key: "hospital_notification", audience: "Receiving hospitals", channel: "hospital_radio", subject: "INCOMING PATIENTS", urgency: "immediate" },
    { key: "public_advisory", audience: "Public", channel: "emergency_alert", subject: "EMERGENCY ADVISORY", urgency: "immediate" },
    { key: "administration_update", audience: "Hospital command center", channel: "email", subject: "SURGE STATUS", urgency: "normal" },
  ] as const;
  return entries.flatMap((entry, index) => {
    const raw = record[entry.key];
    if (typeof raw === "string" && raw.trim()) {
      return [{
        id: `draft-comms-${index}`,
        audience: entry.audience,
        channel: entry.channel,
        subject: entry.subject,
        urgency: entry.urgency,
        body: raw.trim(),
      }];
    }
    const draft = asRecord(raw);
    if (!draft) return [];
    const body = asString(draft.body);
    if (!body) return [];
    return [{
      id: `draft-comms-${index}`,
      audience: asString(draft.audience) || entry.audience,
      channel: asString(draft.channel) || entry.channel,
      subject: asString(draft.subject) || entry.subject,
      urgency: asString(draft.urgency) || entry.urgency,
      body,
    }];
  });
}

function buildLiveDraftPlan(
  incident: Incident,
  runs: AgentRun[],
  committedPlan: PlanVersion | null,
  activeVersion: number | null,
): PlanVersion | null {
  if (runs.length === 0) return null;

  const parserArtifact = asRecord(latestRunByType(runs, "incident_parser")?.output_artifact);
  const riskArtifact = asRecord(latestRunByType(runs, "risk_assessor")?.output_artifact);
  const plannerArtifact = asRecord(latestRunByType(runs, "action_planner")?.output_artifact);
  const commsArtifact = asRecord(latestRunByType(runs, "communications")?.output_artifact);

  if (!parserArtifact && !riskArtifact && !plannerArtifact && !commsArtifact) return null;

  const medicalImpact = asRecord(parserArtifact?.medical_impact);
  const patientFlow = asRecord(plannerArtifact?.patient_flow);
  const patientTransport = asRecord(plannerArtifact?.patient_transport);
  const liveVersion = activeVersion ?? committedPlan?.version ?? incident.current_plan_version + 1;
  const latestTimestamp =
    [...runs]
      .reverse()
      .map((run) => run.completed_at || run.started_at)
      .find(Boolean) || incident.updated_at;

  const critical =
    asNumber(parserArtifact?.critical, asNumber(medicalImpact?.critical, asNumber(plannerArtifact?.critical, asNumber(patientFlow?.critical))));
  const moderate =
    asNumber(parserArtifact?.moderate, asNumber(medicalImpact?.moderate, asNumber(plannerArtifact?.moderate, asNumber(patientFlow?.moderate))));
  const minor =
    asNumber(parserArtifact?.minor, asNumber(medicalImpact?.minor, asNumber(plannerArtifact?.minor, asNumber(patientFlow?.minor))));
  const total =
    asNumber(
      parserArtifact?.incoming_patient_count,
      asNumber(parserArtifact?.patient_count, asNumber(plannerArtifact?.total_patients, asNumber(patientFlow?.total_incoming, critical + moderate + minor))),
    );

  const facilityAssignments =
    Array.isArray(patientFlow?.facility_assignments)
      ? patientFlow.facility_assignments.flatMap((item) => {
          const record = asRecord(item);
          if (!record) return [];
          const hospital = asString(record.hospital);
          if (!hospital) return [];
          return [{
            hospital,
            patients_assigned: asNumber(record.patients_assigned),
            capacity_strain: (asString(record.capacity_strain) || "normal") as FacilityAssignment["capacity_strain"],
            patient_types: asStringArray(record.patient_types),
            routing_reason: asString(record.routing_reason),
            reroute_trigger: asString(record.reroute_trigger),
          }];
        })
      : Array.isArray(plannerArtifact?.facility_assignments)
      ? plannerArtifact.facility_assignments.flatMap((item) => {
          const record = asRecord(item);
          if (!record) return [];
          const hospital = asString(record.hospital);
          if (!hospital) return [];
          return [{
            hospital,
            patients_assigned: asNumber(record.patients_assigned, asNumber(record.patients)),
            capacity_strain: (asString(record.capacity_strain) || asString(record.strain) || "normal") as FacilityAssignment["capacity_strain"],
            patient_types: asStringArray(record.patient_types),
            routing_reason: asString(record.routing_reason) || asString(record.reason),
            reroute_trigger: asString(record.reroute_trigger),
          }];
        })
      : [];

  const confirmedFacts = uniqueStrings([
    ...asStringArray(parserArtifact?.confirmed_facts),
    incident.incident_type ? `Incident reported as ${incident.incident_type}` : "",
    incident.location ? `Location reported as ${incident.location}` : "",
    asBoolean(parserArtifact?.immediate_life_safety_threat) || asBoolean(parserArtifact?.immediate_threat)
      ? "Immediate life safety threat reported"
      : "",
  ]).slice(0, 5);

  const riskNotes = uniqueStrings([
    ...asStringArray(riskArtifact?.primary_risks),
    ...asStringArray(riskArtifact?.top_risks),
    ...asStringArray(patientFlow?.bottlenecks),
  ]);

  const draft: PlanVersion = {
    id: `draft-${incident.id}-${liveVersion}`,
    incident_id: incident.id,
    version: liveVersion,
    created_at: latestTimestamp,
    trigger: committedPlan ? "live update" : "initial",
    incident_summary:
      asString(plannerArtifact?.incident_summary) ||
      asString(plannerArtifact?.summary) ||
      firstSentence(incident.report, 220) ||
      `${incident.incident_type} at ${incident.location}`,
    operational_period:
      asString(parserArtifact?.operational_period) ||
      committedPlan?.operational_period ||
      "Current operational period",
    incident_objectives: asStringArray(riskArtifact?.incident_objectives),
    operational_priorities: uniqueStrings([
      ...asStringArray(plannerArtifact?.operational_priorities),
      ...asStringArray(plannerArtifact?.priorities),
      riskNotes[0] ? `Control: ${riskNotes[0]}` : "",
      "Route highest-acuity patients first",
    ]).slice(0, 4),
    immediate_actions: parseDraftActions(plannerArtifact?.immediate_actions, "Operations", "0-10 min"),
    short_term_actions: parseDraftActions(plannerArtifact?.short_term_actions, "Operations", "10-30 min"),
    ongoing_actions: parseDraftActions(plannerArtifact?.ongoing_actions, "Operations", "30-120 min"),
    resource_assignments: asRecord(plannerArtifact?.resource_assignments) as PlanVersion["resource_assignments"],
    role_assignments: [],
    safety_considerations: asStringArray(riskArtifact?.safety_considerations),
    communications: parseDraftCommunications(commsArtifact),
    confirmed_facts: confirmedFacts,
    unknowns: uniqueStrings([
      ...asStringArray(parserArtifact?.unknowns),
      ...asStringArray(plannerArtifact?.missing_information),
    ]),
    assumptions: parseDraftAssumptions(plannerArtifact?.assumptions),
    missing_information: asStringArray(plannerArtifact?.missing_information),
    assessed_severity:
      asString(riskArtifact?.severity_level) ||
      asString(riskArtifact?.severity) ||
      incident.severity_hint ||
      "medium",
    confidence_score: typeof riskArtifact?.confidence === "number" ? riskArtifact.confidence : 0.65,
    risk_notes: riskNotes,
    patient_flow: {
      total_incoming: total,
      critical,
      moderate,
      minor,
      facility_assignments: facilityAssignments,
      bottlenecks: uniqueStrings([
        ...asStringArray(patientFlow?.bottlenecks),
        ...asStringArray(riskArtifact?.capacity_bottlenecks),
        ...asStringArray(riskArtifact?.bottlenecks),
      ]),
      distribution_rationale:
        asString(patientFlow?.distribution_rationale) ||
        asString(plannerArtifact?.distribution_note) ||
        "Live allocation is still updating as agent outputs arrive.",
    },
    decision_points:
      Array.isArray(plannerArtifact?.decision_points)
        ? plannerArtifact.decision_points.flatMap((item) => {
            const record = asRecord(item);
            if (!record) return [];
            const decision = asString(record.decision);
            if (!decision) return [];
            return [{
              decision,
              reason: asString(record.reason),
              assumption: asString(record.assumption),
              replan_trigger: asString(record.replan_trigger),
            }];
          })
        : asString(plannerArtifact?.key_decision)
        ? [{
            decision: asString(plannerArtifact?.key_decision),
            reason: asString(plannerArtifact?.summary) || "Decision draft is still being refined.",
            assumption: "",
            replan_trigger: asString(plannerArtifact?.replan_if),
          }]
        : [],
    command_recommendations: incident.command_mode || incident.staging_area || incident.transport_group_active
      ? {
          command_mode: incident.command_mode || "pending",
          command_post_established: incident.command_post_established ?? false,
          unified_command_recommended: incident.unified_command ?? false,
          safety_officer_recommended: incident.safety_officer_assigned ?? false,
          staging_area: incident.staging_area || "",
          transport_group_active: incident.transport_group_active ?? false,
          rationale: incident.operational_objectives ?? [],
        }
      : null,
    owned_actions: {},
    command_transfer_summary: null,
    tradeoffs:
      Array.isArray(plannerArtifact?.tradeoffs)
        ? plannerArtifact.tradeoffs.flatMap((item) => {
            const record = asRecord(item);
            if (!record) return [];
            const description = asString(record.description);
            if (!description) return [];
            return [{
              description,
              option_a: asString(record.option_a),
              option_b: asString(record.option_b),
              recommendation: asString(record.recommendation),
            }];
          })
        : [],
    medical_impact: {
      affected_population:
        asString(medicalImpact?.affected_population) ||
        asString(parserArtifact?.affected_population) ||
        "Unknown",
      estimated_injured:
        asString(medicalImpact?.estimated_injured) ||
        asString(parserArtifact?.estimated_injured) ||
        String(total),
      critical,
      moderate,
      minor,
      at_risk_groups: uniqueStrings([
        ...asStringArray(medicalImpact?.at_risk_groups),
        ...asStringArray(parserArtifact?.at_risk_groups),
      ]),
    },
    triage_priorities:
      Array.isArray(plannerArtifact?.triage_priorities)
        ? plannerArtifact.triage_priorities.flatMap((item) => {
            const record = asRecord(item);
            if (!record) return [];
            const priority = asNumber(record.priority);
            if (!priority) return [];
            return [{
              priority,
              label: asString(record.label) || `priority ${priority}`,
              estimated_count: asNumber(record.estimated_count),
              required_response: asString(record.required_response),
              required_action: asString(record.required_action),
            }];
          })
        : [
            { priority: 1, label: "critical", estimated_count: critical, required_response: "Immediate ALS transport", required_action: "Move highest-acuity patients first" },
            { priority: 2, label: "moderate", estimated_count: moderate, required_response: "Rapid stabilization", required_action: "Transport as capacity allows" },
            { priority: 3, label: "minor", estimated_count: minor, required_response: "Delayed transport", required_action: "Hold, monitor, and transport after higher-acuity patients" },
          ],
    patient_transport: {
      primary_facilities: uniqueStrings([
        ...asStringArray(patientTransport?.primary_facilities),
        ...facilityAssignments.map((item) => item.hospital),
      ]).slice(0, 3),
      alternate_facilities: asStringArray(patientTransport?.alternate_facilities),
      transport_routes: uniqueStrings([
        ...asStringArray(patientTransport?.transport_routes),
        asString(plannerArtifact?.primary_access_route),
        asString(plannerArtifact?.primary_route),
      ]),
      constraints: uniqueStrings([
        ...asStringArray(patientTransport?.constraints),
        ...asStringArray(riskArtifact?.transport_delays),
      ]),
      fallback_if_primary_unavailable:
        asString(patientTransport?.fallback_if_primary_unavailable) ||
        asString(plannerArtifact?.alternate_access_route) ||
        asString(plannerArtifact?.alternate_route),
    },
    diff_summary: committedPlan
      ? "Live replan in progress. Decision cards are updating as each agent completes."
      : "Live incident build in progress. New sections will populate as agent results land.",
    changed_sections: ["live_update"],
    first_response_ready: true,
    enrichment_pending: true,
    fallback_mode: runs.some((run) => run.fallback_used),
    recommendation_confidence: committedPlan?.recommendation_confidence ?? 0.65,
    route_confidence: committedPlan?.route_confidence ?? "medium",
    unavailable_components: uniqueStrings(
      runs.filter((run) => runIsActuallyUnavailable(run)).map((run) => UNIT_LABELS[run.agent_type] ?? run.agent_type),
    ),
    verified_information: committedPlan?.verified_information ?? confirmedFacts,
    assumed_information: committedPlan?.assumed_information ?? uniqueStrings([
      ...asStringArray(parserArtifact?.unknowns),
      ...asStringArray(plannerArtifact?.missing_information),
    ]),
    fallback_summary: committedPlan?.fallback_summary ?? null,
    incident_log: incident.incident_log ?? [],
    external_context: {
      ...committedPlan?.external_context,
      replan_triggers: uniqueStrings([
        ...(committedPlan?.external_context?.replan_triggers ?? []),
        ...asStringArray(riskArtifact?.replan_triggers),
      ]),
      healthcare_risks: uniqueStrings([
        ...(committedPlan?.external_context?.healthcare_risks ?? []),
        ...asStringArray(riskArtifact?.healthcare_risks),
      ]),
      weather_driven_threats: uniqueStrings([
        ...(committedPlan?.external_context?.weather_driven_threats ?? []),
        ...asStringArray(riskArtifact?.weather_driven_threats),
      ]),
      primary_access_route:
        asString(plannerArtifact?.primary_access_route) ||
        asString(plannerArtifact?.primary_route) ||
        committedPlan?.external_context?.primary_access_route,
      alternate_access_route:
        asString(plannerArtifact?.alternate_access_route) ||
        asString(plannerArtifact?.alternate_route) ||
        committedPlan?.external_context?.alternate_access_route,
      dedalus_execution:
        [...runs].reverse().find((run) => run.runtime)?.runtime ||
        committedPlan?.external_context?.dedalus_execution,
    },
  };

  return draft;
}

function derivePrimaryActions(plan: PlanVersion) {
  const seen = new Set<string>();
  return [...plan.immediate_actions, ...plan.short_term_actions]
    .filter((action) => {
      const key = stripOrdering(action.description).toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 5);
}

function derivePatientFlow(plan: PlanVersion): PatientFlowSummary | null {
  if (plan.patient_flow) return plan.patient_flow;

  const critical = plan.triage_priorities.find((p) => p.priority === 1)?.estimated_count ?? plan.medical_impact?.critical ?? 0;
  const moderate = plan.triage_priorities.find((p) => p.priority === 2)?.estimated_count ?? plan.medical_impact?.moderate ?? 0;
  const minor = plan.triage_priorities.find((p) => p.priority === 3)?.estimated_count ?? plan.medical_impact?.minor ?? 0;
  const total = critical + moderate + minor;

  const primaryFacilities = uniqueStrings(plan.patient_transport?.primary_facilities ?? []);
  const alternateFacilities = uniqueStrings(plan.patient_transport?.alternate_facilities ?? []);
  const nearbyFacilities = uniqueStrings((plan.external_context?.hospitals ?? []).map((hospital) => hospital.name));
  const hospitals = uniqueStrings([...primaryFacilities, ...alternateFacilities, ...nearbyFacilities]).slice(0, 3);

  if (!total && hospitals.length === 0) return null;

  const assignments: FacilityAssignment[] = [];
  if (hospitals.length === 1) {
    assignments.push({
      hospital: hospitals[0],
      patients_assigned: total,
      capacity_strain: critical > 0 ? "critical" : total > 2 ? "elevated" : "normal",
      patient_types: uniqueStrings([
        critical > 0 ? "Critical" : "",
        moderate > 0 ? "Moderate" : "",
        minor > 0 ? "Minor" : "",
      ]),
      routing_reason: compactText(plan.decision_points?.[0]?.reason || plan.patient_transport?.constraints?.[0] || plan.incident_summary, 72),
      reroute_trigger: compactText(plan.decision_points?.[0]?.replan_trigger || plan.patient_transport?.fallback_if_primary_unavailable || "", 72),
    });
  } else {
    const defaultMix = [
      { count: critical, types: critical > 0 ? ["Critical"] : [] },
      { count: hospitals.length > 2 ? moderate : moderate + minor, types: uniqueStrings([moderate > 0 ? "Moderate" : "", hospitals.length > 2 ? "" : minor > 0 ? "Minor" : ""]) },
      { count: hospitals.length > 2 ? minor : 0, types: minor > 0 ? ["Minor"] : [] },
    ];

    hospitals.forEach((hospital, index) => {
      const bucket = defaultMix[index] ?? { count: 0, types: [] as string[] };
      if (!bucket.count && index > 1) return;
      assignments.push({
        hospital,
        patients_assigned: bucket.count,
        capacity_strain:
          index === 0 && critical > 0
            ? "critical"
            : bucket.count > 1
            ? "elevated"
            : "normal",
        patient_types: bucket.types,
        routing_reason: compactText(
          index === 0
            ? plan.decision_points?.[0]?.reason || plan.patient_transport?.constraints?.[0] || plan.incident_summary
            : plan.patient_transport?.constraints?.[0] || plan.incident_summary,
          72,
        ),
        reroute_trigger: compactText(plan.decision_points?.[0]?.replan_trigger || plan.patient_transport?.fallback_if_primary_unavailable || "", 72),
      });
    });
  }

  return {
    total_incoming: total,
    critical,
    moderate,
    minor,
    facility_assignments: assignments,
    bottlenecks: uniqueStrings([...(plan.patient_transport?.constraints ?? []), ...plan.risk_notes]).slice(0, 4),
    distribution_rationale: firstSentence(plan.decision_points?.[0]?.reason || plan.incident_summary, 120),
  };
}

function deriveBottlenecks(plan: PlanVersion, flow: PatientFlowSummary | null) {
  return uniqueStrings([
    ...(flow?.bottlenecks ?? []),
    ...(plan.patient_transport?.constraints ?? []),
    ...plan.risk_notes,
    ...(plan.external_context?.healthcare_risks ?? []),
    ...(plan.external_context?.replan_triggers ?? []).slice(0, 2),
  ]).slice(0, 5);
}

function bottleneckTone(text: string): keyof typeof BOTTLENECK_TONES {
  if (/(blocked|impassable|critical|cardiac|arrest|diversion|collapse|surge|unresponsive|saturated)/i.test(text)) {
    return "critical";
  }
  if (/(delay|strained|capacity|limited|reroute|weather|pending|monitor|worsen)/i.test(text)) {
    return "elevated";
  }
  return "watch";
}

function hospitalEta(plan: PlanVersion, hospital: string) {
  const routeEta = plan.external_context?.routing?.duration_min;
  const match = (plan.external_context?.hospitals ?? []).find((item) => {
    const itemName = normalizeName(item.name);
    const target = normalizeName(hospital);
    return itemName.includes(target) || target.includes(itemName);
  });
  if (match?.distance_mi != null) return `${match.distance_mi} mi`;
  if (routeEta != null) return `~${routeEta} min`;
  return "";
}

function facilityCapacityNote(assignment: FacilityAssignment) {
  return compactText(assignment.routing_reason || assignment.reroute_trigger || "Monitor receiving capacity", 52);
}

function deriveDecisionSummary(plan: PlanVersion, flow: PatientFlowSummary | null, bottlenecks: string[]) {
  const primaryAction = derivePrimaryActions(plan)[0];
  const primaryAssignment = flow?.facility_assignments?.[0];
  const recommendation =
    compactText(
      plan.decision_points?.[0]?.decision ||
        (primaryAssignment
          ? `Route ${primaryAssignment.patient_types.join("/") || "incoming patients"} to ${primaryAssignment.hospital}`
          : stripOrdering(plan.operational_priorities[0]) || firstSentence(plan.incident_summary, 110)),
      120,
    ) || "Confirm destination routing and execute immediate medical actions";

  return {
    decision: recommendation,
    why:
      compactText(
        plan.decision_points?.[0]?.reason ||
          flow?.distribution_rationale ||
          firstSentence(plan.incident_summary, 120) ||
          "Operational recommendation based on current field report and transport context.",
        120,
      ) || "Operational recommendation based on the current incident picture.",
    risk:
      compactText(
        bottlenecks[0] ||
          plan.risk_notes[0] ||
          plan.external_context?.healthcare_risks?.[0] ||
          "Transport and receiving capacity remain the main operational risk.",
        108,
      ) || "Transport and receiving capacity remain the main operational risk.",
    nextAction:
      compactText(
        primaryAction?.description || stripOrdering(plan.operational_priorities[0]) || "Validate access, assign transport, and move highest-acuity patients first.",
        130,
      ) || "Validate access, assign transport, and move highest-acuity patients first.",
    nextOwner: primaryAction?.assigned_to,
    nextTimeframe: primaryAction?.timeframe,
    primaryDestination:
      primaryAssignment?.hospital ||
      plan.patient_transport?.primary_facilities?.[0] ||
      plan.external_context?.hospitals?.[0]?.name ||
      "Destination pending confirmation",
  };
}

function deriveWhatChanged(plan: PlanVersion, diff: PlanDiff | null, runs: AgentRun[], bottlenecks: string[]) {
  const fallbackRuns = runs.filter((run) => run.fallback_used);
  const changedSections = diff?.changed_sections ?? plan.changed_sections ?? [];
  const summary = diff?.summary || plan.diff_summary;

  if (summary || changedSections.length > 0) {
    return {
      change: compactText(summary || `Updated ${changedSections.join(", ")}`, 96),
      impact: compactText(plan.decision_points?.[0]?.reason || firstSentence(plan.incident_summary, 100), 100),
      why: compactText(
        changedSections.length > 0
          ? `Decision shifted across ${changedSections.join(", ")}.`
          : "Recommendation changed because the latest field update altered the operating picture.",
        110,
      ),
      tags: changedSections.slice(0, 4),
    };
  }

  if (fallbackRuns.length > 0) {
    return {
      change: compactText(`Fallback active for ${fallbackRuns.map((run) => UNIT_LABELS[run.agent_type] ?? run.agent_type).join(", ")}`, 96),
      impact: compactText("Live recommendation uses conservative assumptions while degraded agent output is in effect.", 102),
      why: compactText(
        fallbackRuns[0]?.error_message || bottlenecks[0] || "One or more live agent steps timed out.",
        110,
      ),
      tags: fallbackRuns.map((run) => UNIT_LABELS[run.agent_type] ?? run.agent_type).slice(0, 4),
    };
  }

  return {
    change: "Initial operational picture established",
    impact: compactText(firstSentence(plan.incident_summary, 100), 100),
    why: "No prior version to compare.",
    tags: [] as string[],
  };
}

function OperationalStatusCard({ plan }: { plan: PlanVersion }) {
  const verified = (plan.verified_information ?? []).slice(0, 4);
  const assumed = (plan.assumed_information ?? []).slice(0, 4);
  const unavailable = (plan.unavailable_components ?? []).slice(0, 4);
  const fallback = plan.fallback_summary;

  return (
    <section className="command-card print-card rounded-3xl border p-5">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="command-kicker">Operational Status</p>
            <p className="mt-1 text-sm text-muted-foreground/75">Fast answer first, swarm enrichment second</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-full border border-border/75 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-foreground/72">
              confidence {Math.round((plan.recommendation_confidence ?? 0) * 100)}%
            </span>
            <span className="rounded-full border border-border/75 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-foreground/72">
              route {plan.route_confidence ?? "low"}
            </span>
            {plan.enrichment_pending ? (
              <span className="rounded-full border border-cyan-500/30 bg-cyan-500/8 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-cyan-300">
                enrichment pending
              </span>
            ) : (
              <span className="rounded-full border border-green-500/30 bg-green-500/8 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-green-300">
                first answer ready
              </span>
            )}
            {plan.fallback_mode && (
              <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-amber-300">
                fallback mode
              </span>
            )}
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/60">Verified</p>
            <div className="mt-2 space-y-1.5">
              {verified.length > 0 ? verified.map((item, index) => (
                <div key={index} className="flex gap-2 text-xs text-foreground/82">
                  <span className="text-green-400/70 shrink-0">✓</span>
                  <span>{item}</span>
                </div>
              )) : <p className="text-xs text-muted-foreground/65">Verified details are still limited.</p>}
            </div>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/60">Assumed / Unverified</p>
            <div className="mt-2 space-y-1.5">
              {assumed.length > 0 ? assumed.map((item, index) => (
                <div key={index} className="flex gap-2 text-xs text-foreground/78">
                  <span className="text-amber-400/70 shrink-0">?</span>
                  <span>{item}</span>
                </div>
              )) : <p className="text-xs text-muted-foreground/65">No major planning assumptions flagged.</p>}
            </div>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/60">Unavailable / Deferred</p>
            <div className="mt-2 space-y-1.5">
              {unavailable.length > 0 ? unavailable.map((item, index) => (
                <div key={index} className="flex gap-2 text-xs text-foreground/78">
                  <span className="text-red-400/70 shrink-0">×</span>
                  <span>{item}</span>
                </div>
              )) : (
                <p className="text-xs text-muted-foreground/65">
                  {plan.enrichment_pending
                    ? "Swarm enrichment is still running."
                    : plan.fallback_mode
                    ? "Swarm enrichment degraded, but local fallbacks are active."
                    : "No unavailable components reported."}
                </p>
              )}
              {fallback?.safe_to_act_on?.length ? (
                <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-300">Safe To Act On</p>
                  <p className="mt-1 text-xs text-foreground/82">{fallback.safe_to_act_on.slice(0, 3).join("; ")}</p>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function DecisionSummaryCard({
  incident,
  plan,
  alertCount,
  flow,
  bottlenecks,
  runs,
}: {
  incident: Incident;
  plan: PlanVersion;
  alertCount: number;
  flow: PatientFlowSummary | null;
  bottlenecks: string[];
  runs: AgentRun[];
}) {
  const summary = deriveDecisionSummary(plan, flow, bottlenecks);
  const fallbackCount = runs.filter((run) => run.fallback_used).length;
  const lastUpdated = new Date(plan.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  return (
    <section className="command-card command-card-hero print-card space-y-5 rounded-3xl border p-5 sm:p-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="command-kicker">Decision Summary</span>
            <SeverityBadge level={plan.assessed_severity ?? incident.severity_hint} />
            {alertCount > 0 && (
              <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2 py-0.5 text-[10px] font-semibold text-orange-300">
                {alertCount} alert{alertCount > 1 ? "s" : ""}
              </span>
            )}
            {fallbackCount > 0 && (
              <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
                fallback active
              </span>
            )}
          </div>
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-[0.28em] text-muted-foreground/60">Live Healthcare Operations</p>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
              {incident.incident_type}
            </h1>
            <p className="max-w-3xl text-sm text-foreground/72">{incident.location}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:min-w-[18rem]">
          <div className="rounded-2xl border border-border/70 bg-background/35 px-3 py-2">
            <p className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground/55">Primary Destination</p>
            <p className="mt-1 text-sm text-foreground">{summary.primaryDestination}</p>
          </div>
          <div className="rounded-2xl border border-border/70 bg-background/35 px-3 py-2">
            <p className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground/55">Incoming</p>
            <p className="mt-1 text-sm text-foreground">{flow?.total_incoming ?? 0} patients</p>
          </div>
          <div className="rounded-2xl border border-border/70 bg-background/35 px-3 py-2">
            <p className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground/55">Plan Version</p>
            <p className="mt-1 text-sm text-foreground">v{plan.version}</p>
          </div>
          <div className="rounded-2xl border border-border/70 bg-background/35 px-3 py-2">
            <p className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground/55">Last Updated</p>
            <p className="mt-1 text-sm text-foreground">{lastUpdated}</p>
          </div>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[1.45fr,1fr,1fr]">
        <div className="rounded-2xl border border-primary/25 bg-primary/8 p-4 xl:row-span-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-primary/80">Decision</p>
          <p className="mt-3 text-xl font-semibold leading-tight text-foreground sm:text-2xl">
            {summary.decision}
          </p>
        </div>
        <div className="rounded-2xl border border-border/80 bg-background/35 p-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/65">Why</p>
          <p className="mt-2 text-sm leading-relaxed text-foreground/82">{summary.why}</p>
        </div>
        <div className="rounded-2xl border border-border/80 bg-background/35 p-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/65">Risk</p>
          <p className="mt-2 text-sm leading-relaxed text-foreground/82">{summary.risk}</p>
        </div>
        <div className="rounded-2xl border border-border/80 bg-background/35 p-4 xl:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/65">Next Action</p>
            {summary.nextOwner && (
              <span className="rounded-full border border-border/80 px-2 py-0.5 text-[10px] text-foreground/70">
                {summary.nextOwner}
              </span>
            )}
            {summary.nextTimeframe && (
              <span className="rounded-full border border-border/70 px-2 py-0.5 text-[10px] text-muted-foreground/72">
                {summary.nextTimeframe}
              </span>
            )}
          </div>
          <p className="mt-2 text-sm font-medium leading-relaxed text-foreground">{summary.nextAction}</p>
        </div>
      </div>
    </section>
  );
}

function WhatChangedCard({
  plan,
  diff,
  runs,
  bottlenecks,
}: {
  plan: PlanVersion;
  diff: PlanDiff | null;
  runs: AgentRun[];
  bottlenecks: string[];
}) {
  const change = deriveWhatChanged(plan, diff, runs, bottlenecks);

  return (
    <section className="command-card command-card-muted print-card rounded-3xl border p-5">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="command-kicker">What Changed</p>
            <p className="mt-1 text-sm text-muted-foreground/75">Latest shift in decision context</p>
          </div>
          {change.tags.length > 0 && (
            <div className="flex flex-wrap justify-end gap-1.5">
              {change.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full border border-border/80 px-2 py-0.5 text-[10px] text-muted-foreground/78"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/60">New</p>
            <p className="mt-1 text-sm text-foreground">{change.change}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/60">Impact on Decision</p>
            <p className="mt-1 text-sm text-foreground/82">{change.impact}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/60">Why Recommendation Changed</p>
            <p className="mt-1 text-sm text-foreground/82">{change.why}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function PatientFlowOverviewCard({ flow }: { flow: PatientFlowSummary | null }) {
  const total = flow?.total_incoming ?? 0;
  const critical = flow?.critical ?? 0;
  const moderate = flow?.moderate ?? 0;
  const minor = flow?.minor ?? 0;
  const segments = total > 0
    ? [
        { value: critical, classes: "bg-red-400" },
        { value: moderate, classes: "bg-orange-400" },
        { value: minor, classes: "bg-yellow-400" },
      ].filter((segment) => segment.value > 0)
    : [];

  return (
    <section className="command-card print-card rounded-3xl border p-5">
      <div className="space-y-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="command-kicker">Patient Flow Overview</p>
            <p className="mt-1 text-sm text-muted-foreground/75">Current expected incoming patient load</p>
          </div>
          <div className="text-right">
            <p className="text-4xl font-semibold tracking-tight text-foreground">{total}</p>
            <p className="text-[10px] uppercase tracking-[0.24em] text-muted-foreground/60">Total Incoming</p>
          </div>
        </div>

        <div className="overflow-hidden rounded-full border border-border/70 bg-background/45">
          <div className="flex h-3 w-full">
            {segments.length > 0 ? (
              segments.map((segment, index) => (
                <div
                  key={index}
                  className={segment.classes}
                  style={{ width: `${(segment.value / total) * 100}%` }}
                />
              ))
            ) : (
              <div className="h-full w-full bg-border/40" />
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: "Critical", value: critical, classes: "border-red-500/30 bg-red-500/8 text-red-300" },
            { label: "Moderate", value: moderate, classes: "border-orange-500/30 bg-orange-500/8 text-orange-300" },
            { label: "Minor", value: minor, classes: "border-yellow-500/25 bg-yellow-500/8 text-yellow-200" },
            { label: "Total", value: total, classes: "border-border/80 bg-background/40 text-foreground" },
          ].map((metric) => (
            <div key={metric.label} className={`rounded-2xl border px-3 py-3 text-center ${metric.classes}`}>
              <p className="text-3xl font-semibold tracking-tight">{metric.value}</p>
              <p className="mt-1 text-[10px] uppercase tracking-[0.24em]">{metric.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function FacilityAssignmentsCard({ plan, flow }: { plan: PlanVersion; flow: PatientFlowSummary | null }) {
  const assignments = flow?.facility_assignments ?? [];

  return (
    <section className="command-card print-card rounded-3xl border p-5">
      <div className="space-y-4">
        <div>
          <p className="command-kicker">Facility Assignments</p>
          <p className="mt-1 text-sm text-muted-foreground/75">Where patients are going now</p>
        </div>

        {assignments.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border/80 bg-background/35 px-4 py-5 text-sm text-muted-foreground/70">
            Destination assignments are still being confirmed.
          </div>
        ) : (
          <div className="space-y-2">
            <div className="hidden grid-cols-[minmax(0,1.4fr)_5rem_minmax(0,1fr)_6rem_minmax(0,1fr)_4.5rem] gap-3 px-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/55 md:grid">
              <span>Hospital</span>
              <span>Assigned</span>
              <span>Patient Mix</span>
              <span>Status</span>
              <span>Capacity Note</span>
              <span>ETA</span>
            </div>
            {assignments.map((assignment) => {
              const tone = STRAIN_STYLES[assignment.capacity_strain] ?? STRAIN_STYLES.normal;
              const eta = hospitalEta(plan, assignment.hospital);
              return (
                <div
                  key={assignment.hospital}
                  className="grid gap-3 rounded-2xl border border-border/75 bg-background/35 px-3 py-3 md:grid-cols-[minmax(0,1.4fr)_5rem_minmax(0,1fr)_6rem_minmax(0,1fr)_4.5rem] md:items-center"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">{assignment.hospital}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground/68 md:hidden">{facilityCapacityNote(assignment)}</p>
                  </div>
                  <div className="flex items-center gap-2 md:block">
                    <span className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground/55 md:hidden">Assigned</span>
                    <span className="text-lg font-semibold text-foreground">{assignment.patients_assigned}</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {assignment.patient_types.length > 0 ? (
                      assignment.patient_types.slice(0, 3).map((type) => (
                        <span key={type} className="rounded-full border border-border/75 px-2 py-0.5 text-[10px] text-foreground/76">
                          {type}
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px] text-muted-foreground/62">Awaiting mix</span>
                    )}
                  </div>
                  <div>
                    <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] ${tone.border} ${tone.bg} ${tone.text}`}>
                      {assignment.capacity_strain}
                    </span>
                  </div>
                  <div className="hidden text-[11px] text-foreground/72 md:block">{facilityCapacityNote(assignment)}</div>
                  <div className="text-[11px] text-muted-foreground/70">{eta || "—"}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function BottlenecksCard({ bottlenecks }: { bottlenecks: string[] }) {
  return (
    <section className="command-card print-card rounded-3xl border p-5">
      <div className="space-y-4">
        <div>
          <p className="command-kicker">Active Bottlenecks</p>
          <p className="mt-1 text-sm text-muted-foreground/75">Current constraint on medical flow</p>
        </div>

        {bottlenecks.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border/80 bg-background/35 px-4 py-5 text-sm text-muted-foreground/70">
            No active bottlenecks identified in the current plan.
          </div>
        ) : (
          <div className="space-y-2">
            {bottlenecks.slice(0, 4).map((bottleneck, index) => {
              const tone = BOTTLENECK_TONES[bottleneckTone(bottleneck)];
              return (
                <div
                  key={`${bottleneck}-${index}`}
                  className="flex items-center gap-3 rounded-2xl border border-border/75 bg-background/35 px-3 py-3"
                >
                  <span className={`h-9 w-1.5 rounded-full ${tone.bar}`} />
                  <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] ${tone.badge}`}>
                    {bottleneckTone(bottleneck)}
                  </span>
                  <p className="truncate text-sm text-foreground">{compactText(bottleneck, 108)}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function ImmediateActionsCard({ actions, diff }: { actions: ActionItem[]; diff: PlanDiff | null }) {
  return (
    <section className="command-card print-card rounded-3xl border p-5">
      <div className="space-y-4">
        <div>
          <p className="command-kicker">Immediate Actions</p>
          <p className="mt-1 text-sm text-muted-foreground/75">Top operational moves for the next 30 minutes</p>
        </div>
        {actions.length > 0 ? (
          <PriorityActions actions={actions} diff={diff} />
        ) : (
          <div className="rounded-2xl border border-dashed border-border/80 bg-background/35 px-4 py-5 text-sm text-muted-foreground/70">
            No immediate actions are available yet.
          </div>
        )}
      </div>
    </section>
  );
}

// ---- IAP sub-components ----

function IncidentObjectives({ objectives }: { objectives: string[] }) {
  if (!objectives.length) return null;
  return (
    <div className="space-y-1.5">
      {objectives.map((obj, i) => {
        const [prefix, ...rest] = obj.split(":");
        const hasPrefix = rest.length > 0 && prefix.length < 40;
        return (
          <div key={i} className="flex gap-3 items-start text-xs">
            <span className="shrink-0 w-5 h-5 rounded-full bg-primary/15 text-primary flex items-center justify-center text-[10px] font-bold mt-0.5">
              {i + 1}
            </span>
            <span className="text-foreground/90">
              {hasPrefix ? (
                <><span className="font-semibold text-foreground/60 uppercase tracking-wide text-[10px]">{prefix}:</span>{" "}{rest.join(":")}</>
              ) : obj}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function OperationalPriorities({ priorities }: { priorities: string[] }) {
  return (
    <div className="space-y-2">
      {priorities.map((p, i) => {
        const text = p.replace(/^\d+\.\s*/, "");
        return (
          <div key={i} className="flex gap-2.5 text-xs items-start">
            <span className={`shrink-0 font-bold text-[10px] w-5 h-5 rounded flex items-center justify-center mt-0.5 ${
              i === 0 ? "bg-red-500/20 text-red-400" : i === 1 ? "bg-orange-500/15 text-orange-400" : "bg-border text-muted-foreground"
            }`}>
              {i + 1}
            </span>
            <span className="text-foreground/90">{text}</span>
          </div>
        );
      })}
      <p className="text-[10px] text-muted-foreground/70 ml-7 pt-1">
        Escalation and replan triggers are listed under Threat Analysis above.
      </p>
    </div>
  );
}

function ExecutionPhase({
  label,
  sublabel,
  items,
  added,
  removed,
}: {
  label: string;
  sublabel: string;
  items: ActionItem[];
  added: Set<string>;
  removed: Set<string>;
}) {
  if (!items.length) return null;
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{label}</p>
        <p className="text-[10px] text-muted-foreground/50">{sublabel}</p>
      </div>
      <div className="space-y-1.5">
        {items.map((item) => (
          <div
            key={item.id}
            className={`flex gap-2.5 text-xs p-2 rounded ${
              added.has(item.description)
                ? "bg-green-500/8 text-foreground"
                : removed.has(item.description)
                ? "line-through text-muted-foreground/50"
                : "text-foreground/80"
            }`}
          >
            <span className="text-muted-foreground/40 shrink-0 mt-0.5 w-3">
              {added.has(item.description) ? <span className="text-green-400">+</span> : "→"}
            </span>
            <span className="flex-1">{item.description}</span>
            <div className="text-[10px] text-muted-foreground/50 shrink-0 text-right min-w-fit">
              {item.assigned_to && <div>{item.assigned_to}</div>}
              {item.timeframe && <div className="text-muted-foreground/35">{item.timeframe}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ExecutionPlan({ plan, diff }: { plan: PlanVersion; diff: PlanDiff | null }) {
  const added = new Set(diff?.added_actions.map((a) => a.description) ?? []);
  const removed = new Set(diff?.removed_actions.map((a) => a.description) ?? []);

  return (
    <div className="space-y-5">
      <ExecutionPhase label="Immediate" sublabel="0–10 min" items={plan.immediate_actions} added={added} removed={removed} />
      <ExecutionPhase label="Short-Term" sublabel="10–30 min" items={plan.short_term_actions} added={added} removed={removed} />
      <ExecutionPhase label="Ongoing" sublabel="30–120 min" items={plan.ongoing_actions} added={added} removed={removed} />
    </div>
  );
}

function ResourceAssignments({ assignments, roleAssignments }: {
  assignments?: PlanVersion["resource_assignments"];
  roleAssignments: PlanVersion["role_assignments"];
}) {
  const sections = assignments
    ? (["operations", "logistics", "communications", "command"] as const).filter(
        (k) => assignments[k]?.length
      )
    : [];

  if (sections.length === 0 && roleAssignments.length === 0) {
    return <p className="text-xs text-muted-foreground">No resource assignments.</p>;
  }

  if (sections.length > 0 && assignments) {
    const labels: Record<string, string> = {
      operations: "Operations",
      logistics: "Logistics",
      communications: "Communications",
      command: "Command",
    };
    return (
      <div className="space-y-4">
        {sections.map((section) => (
          <div key={section}>
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">
              {labels[section]}
            </p>
            <div className="space-y-1">
              {(assignments[section] ?? []).map((item, i) => {
                const [unit, ...rest] = item.split("→");
                const hasArrow = rest.length > 0;
                return (
                  <div key={i} className="flex gap-2 text-xs">
                    <span className="text-primary shrink-0">{unit.trim()}</span>
                    {hasArrow && (
                      <>
                        <span className="text-muted-foreground/40">→</span>
                        <span className="text-foreground/70">{rest.join("→").trim()}</span>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {roleAssignments.map((r, i) => (
        <div key={i} className="text-xs flex gap-2">
          <span className="text-primary shrink-0">{r.role}</span>
          <span className="text-muted-foreground/40">→</span>
          <span className="text-foreground/80">{r.assigned_to}</span>
        </div>
      ))}
    </div>
  );
}

function SafetyConsiderations({ items }: { items: string[] }) {
  if (!items.length) return <p className="text-xs text-muted-foreground">No safety data.</p>;
  return (
    <div className="space-y-1.5">
      {items.map((item, i) => {
        const [prefix, ...rest] = item.split(":");
        const hasPrefix = rest.length > 0 && prefix.length < 30;
        return (
          <div key={i} className="flex gap-2.5 text-xs items-start">
            <span className="text-red-400/70 shrink-0 mt-0.5">⚠</span>
            <span className="text-foreground/85">
              {hasPrefix ? (
                <><span className="font-semibold text-foreground/50 uppercase text-[10px] tracking-wide">{prefix}:</span>{" "}{rest.join(":")}</>
              ) : item}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SituationStatus({ plan }: { plan: PlanVersion }) {
  return (
    <div className="space-y-4">
      {plan.confirmed_facts.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Confirmed Facts</p>
          <div className="space-y-1">
            {plan.confirmed_facts.map((f, i) => (
              <div key={i} className="flex gap-2 text-xs">
                <span className="text-green-400/60 shrink-0">✓</span>
                <span className="text-foreground/85">{f}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {(plan.unknowns.length > 0 || plan.missing_information.length > 0) && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Unknowns / Unconfirmed</p>
          <div className="space-y-1">
            {plan.unknowns.map((u, i) => (
              <div key={i} className="flex gap-2 text-xs">
                <span className="text-orange-400/70 shrink-0">?</span>
                <span className="text-foreground/80">{u}</span>
              </div>
            ))}
            {plan.missing_information.map((m, i) => (
              <div key={i} className="flex gap-2 text-xs">
                <span className="text-orange-400/50 shrink-0">!</span>
                <span className="text-muted-foreground/70">Verify: {m}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {plan.assumptions.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Planning Assumptions</p>
          <div className="space-y-1">
            {plan.assumptions.map((a) => (
              <div key={a.id} className="text-xs text-muted-foreground/70">
                <span className="text-foreground/60">{a.description}</span>
                {a.impact && <span className="text-muted-foreground/40"> — If wrong: {a.impact}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CommsSummary({ plan }: { plan: PlanVersion }) {
  const [expanded, setExpanded] = useState(false);
  const comms = plan.communications;
  if (!comms.length) return <p className="text-xs text-muted-foreground">No communications drafted.</p>;

  const audienceMap: Record<string, string> = {
    "ems responders": "EMS",
    ems: "EMS",
    responders: "EMS",
    "receiving hospitals": "Hospitals",
    hospital: "Hospitals",
    "campus community": "Public",
    public: "Public",
    administration: "Leadership",
    "agency leadership": "Leadership",
  };

  const getLabel = (audience: string) =>
    Object.entries(audienceMap).find(([k]) => audience.toLowerCase().includes(k))?.[1] ?? audience;

  return (
    <div className="space-y-2">
      {comms.map((c) => (
        <div key={c.id} className="text-xs">
          <div className="flex gap-2 items-baseline">
            <span className="text-muted-foreground/60 shrink-0 w-20">{getLabel(c.audience)}</span>
            <span className="text-foreground/80 line-clamp-1">{c.body.split(".")[0]}.</span>
          </div>
        </div>
      ))}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="text-[11px] text-muted-foreground hover:text-foreground transition-colors mt-1"
      >
        {expanded ? "Collapse" : "View full messages →"}
      </button>
      {expanded && (
        <div className="pt-3 border-t border-border">
          <CommunicationsPanel communications={comms} />
        </div>
      )}
    </div>
  );
}

function DiffSummary({ diff }: { diff: PlanDiff }) {
  const [expanded, setExpanded] = useState(false);
  const totalChanges = diff.added_actions.length + diff.removed_actions.length + diff.changed_sections.length;

  return (
    <div className="text-xs space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-cyan-400">IAP Revised</span>
        <span className="text-muted-foreground/60">
          v{diff.from_version} → v{diff.to_version} · {totalChanges} change{totalChanges !== 1 ? "s" : ""}
        </span>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-muted-foreground hover:text-foreground transition-colors ml-auto"
        >
          {expanded ? "Hide" : "Show changes"}
        </button>
      </div>
      {diff.summary && <p className="text-muted-foreground/70">{diff.summary}</p>}

      {expanded && (
        <div className="space-y-2 pt-2 border-t border-border">
          {diff.added_actions.map((a) => (
            <div key={a.id} className="flex gap-2">
              <span className="text-green-400 shrink-0">+</span>
              <span className="text-foreground/80">{a.description}</span>
            </div>
          ))}
          {diff.removed_actions.map((a) => (
            <div key={a.id} className="flex gap-2">
              <span className="text-red-400 shrink-0">−</span>
              <span className="text-muted-foreground/50 line-through">{a.description}</span>
            </div>
          ))}
          {diff.updated_priorities && (
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-widest mb-1">Updated Priorities</p>
              {diff.updated_priorities.map((p, i) => (
                <div key={i} className="text-foreground/80">{i + 1}. {p.replace(/^\d+\.\s*/, "")}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const STRAIN_STYLES = {
  normal: { border: "border-green-500/30", bg: "bg-green-500/5", dot: "bg-green-500", text: "text-green-400" },
  elevated: { border: "border-orange-500/30", bg: "bg-orange-500/5", dot: "bg-orange-500", text: "text-orange-400" },
  critical: { border: "border-red-500/30", bg: "bg-red-500/8", dot: "bg-red-500", text: "text-red-400" },
};

function DecisionPointsPanel({ points }: { points: DecisionPoint[] }) {
  if (!points.length) return null;
  return (
    <div className="space-y-2">
      {points.map((dp, i) => (
        <div key={i} className="p-3 rounded border border-border bg-card/40 text-xs space-y-1.5">
          <p className="font-semibold text-foreground">{dp.decision}</p>
          <p className="text-foreground/65">{dp.reason}</p>
          {dp.assumption && (
            <p className="text-muted-foreground/60"><span className="font-medium text-muted-foreground">Assumes:</span> {dp.assumption}</p>
          )}
          {dp.replan_trigger && (
            <p className="text-amber-400/80"><span className="font-medium">Replan if:</span> {dp.replan_trigger}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function TradeoffsPanel({ tradeoffs }: { tradeoffs: Tradeoff[] }) {
  if (!tradeoffs.length) return null;
  return (
    <div className="space-y-3">
      {tradeoffs.map((t, i) => (
        <div key={i} className="p-3 rounded border border-border bg-card/40 text-xs space-y-2">
          <p className="font-semibold text-foreground text-[11px] uppercase tracking-wide text-muted-foreground">{t.description}</p>
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2 rounded border border-border/50">
              <p className="text-[9px] text-muted-foreground uppercase tracking-widest mb-0.5">Option A</p>
              <p className="text-foreground/80">{t.option_a}</p>
            </div>
            <div className="p-2 rounded border border-border/50">
              <p className="text-[9px] text-muted-foreground uppercase tracking-widest mb-0.5">Option B</p>
              <p className="text-foreground/80">{t.option_b}</p>
            </div>
          </div>
          <div className="flex gap-2 items-start">
            <span className="text-green-400/80 shrink-0 text-[10px] font-bold uppercase mt-0.5">→</span>
            <p className="text-foreground/85">{t.recommendation}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function ICSCommandPanel({
  command,
  ownedActions,
  transfer,
}: {
  command: CommandRecommendations | null | undefined;
  ownedActions: Record<string, string[]> | undefined;
  transfer: CommandTransferSummary | null | undefined;
}) {
  const actionGroups = Object.entries(ownedActions ?? {}).filter(([, items]) => items.length > 0);
  if (!command && !transfer && actionGroups.length === 0) return null;

  return (
    <div className="space-y-5">
      {command && (
        <div className="space-y-3">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {[
              ["Command Mode", command.command_mode || "pending"],
              ["Command Post", command.command_post_established ? "establish / active" : "not yet established"],
              ["Unified Command", command.unified_command_recommended ? "recommended" : "not required"],
              ["Safety Officer", command.safety_officer_recommended ? "recommended" : "not required"],
              ["Transport Group", command.transport_group_active ? "activate" : "stand by"],
              ["Staging", command.staging_area || "not yet defined"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-border/75 bg-background/35 px-3 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/60">{label}</p>
                <p className="mt-1 text-sm text-foreground">{value}</p>
              </div>
            ))}
          </div>
          {command.rationale.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Why</p>
              {command.rationale.map((item, index) => (
                <div key={index} className="flex gap-2 text-xs text-foreground/82">
                  <span className="text-primary/70 shrink-0">•</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {actionGroups.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Owned Actions</p>
          <div className="grid gap-3 xl:grid-cols-2">
            {actionGroups.map(([group, items]) => (
              <div key={group} className="rounded-2xl border border-border/75 bg-background/35 px-3 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/65">{group}</p>
                <div className="mt-2 space-y-1.5">
                  {items.slice(0, 3).map((item, index) => (
                    <div key={index} className="flex gap-2 text-xs text-foreground/82">
                      <span className="text-primary/70 shrink-0">→</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {transfer && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Transfer Brief</p>
          <div className="rounded-2xl border border-border/75 bg-background/35 px-4 py-4 space-y-2 text-xs">
            <p className="text-foreground"><span className="text-muted-foreground/70">Strategy:</span> {transfer.current_strategy}</p>
            {transfer.top_hazards.length > 0 && (
              <p className="text-foreground"><span className="text-muted-foreground/70">Top Hazards:</span> {transfer.top_hazards.join("; ")}</p>
            )}
            {transfer.active_groups.length > 0 && (
              <p className="text-foreground"><span className="text-muted-foreground/70">Active Groups:</span> {transfer.active_groups.join(", ")}</p>
            )}
            {transfer.next_decisions.length > 0 && (
              <div>
                <p className="text-muted-foreground/70">Next Decisions</p>
                <div className="mt-1 space-y-1">
                  {transfer.next_decisions.map((item, index) => (
                    <div key={index} className="flex gap-2 text-foreground/82">
                      <span className="text-amber-400/70 shrink-0">•</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function IncidentLogPanel({ entries }: { entries: IncidentLogEntry[] }) {
  if (!entries.length) return <p className="text-xs text-muted-foreground">No incident log entries yet.</p>;
  return (
    <div className="space-y-2">
      {[...entries].slice(-10).reverse().map((entry, index) => (
        <div key={`${entry.timestamp}-${index}`} className="rounded-2xl border border-border/75 bg-background/35 px-3 py-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground/60">{new Date(entry.timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
            <span className="rounded-full border border-border/75 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/72">
              {entry.category}
            </span>
            <span className="text-muted-foreground/72">{entry.source}</span>
          </div>
          <p className="mt-2 text-foreground/86">{entry.message}</p>
        </div>
      ))}
    </div>
  );
}

function MedicalImpactPanel({ impact }: { impact: MedicalImpact }) {
  const total = impact.critical + impact.moderate + impact.minor;
  const hasCounts = total > 0;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-0.5">Estimated Affected Population</p>
          <p className="text-xs text-foreground/90">{impact.affected_population || "—"}</p>
        </div>
        <div>
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-0.5">Estimated Injured (range)</p>
          <p className="text-xs text-foreground/90">{impact.estimated_injured || "—"}</p>
        </div>
      </div>

      {hasCounts && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Injury Severity Breakdown</p>
          <div className="grid grid-cols-3 gap-2">
            <div className="p-2 rounded border border-red-500/30 bg-red-500/8 text-center">
              <p className="text-lg font-bold text-red-400">{impact.critical}</p>
              <p className="text-[9px] text-red-400/70 uppercase tracking-widest">Critical</p>
            </div>
            <div className="p-2 rounded border border-orange-500/30 bg-orange-500/8 text-center">
              <p className="text-lg font-bold text-orange-400">{impact.moderate}</p>
              <p className="text-[9px] text-orange-400/70 uppercase tracking-widest">Moderate</p>
            </div>
            <div className="p-2 rounded border border-yellow-500/25 bg-yellow-500/5 text-center">
              <p className="text-lg font-bold text-yellow-400">{impact.minor}</p>
              <p className="text-[9px] text-yellow-400/70 uppercase tracking-widest">Minor</p>
            </div>
          </div>
        </div>
      )}

      {impact.at_risk_groups.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1">At-Risk Groups</p>
          <div className="flex flex-wrap gap-1.5">
            {impact.at_risk_groups.map((g, i) => (
              <span key={i} className="text-[10px] px-2 py-0.5 rounded border border-border text-muted-foreground/80">{g}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ThreatAnalysisPanel({
  primaryRisks,
  healthcareRisks,
  replanTriggers,
  weatherThreats,
}: {
  primaryRisks: string[];
  healthcareRisks: string[];
  replanTriggers: string[];
  weatherThreats: string[];
}) {
  const hasAny =
    primaryRisks.length > 0 ||
    healthcareRisks.length > 0 ||
    replanTriggers.length > 0 ||
    weatherThreats.length > 0;
  if (!hasAny) {
    return <p className="text-xs text-muted-foreground">No threat analysis data.</p>;
  }
  return (
    <div className="space-y-3 text-xs">
      {primaryRisks.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Priority Risks</p>
          <ul className="space-y-1">
            {primaryRisks.map((r, i) => (
              <li key={i} className="flex gap-2 text-foreground/85">
                <span className="text-orange-400/80 shrink-0">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {healthcareRisks.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Healthcare / EMS Risks</p>
          <ul className="space-y-1">
            {healthcareRisks.map((r, i) => (
              <li key={i} className="flex gap-2 text-foreground/85">
                <span className="text-red-400/70 shrink-0">+</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(weatherThreats.length > 0 || replanTriggers.length > 0) && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Replan & Escalation</p>
          {weatherThreats.map((t, i) => (
            <div key={`w-${i}`} className="flex gap-2 text-[11px] text-orange-300/90 mb-1">
              <span className="shrink-0">NWS</span>
              <span>{t}</span>
            </div>
          ))}
          {replanTriggers.slice(0, 6).map((t, i) => (
            <div key={i} className="flex gap-2 text-[11px] text-amber-400/80 mt-0.5">
              <span className="shrink-0">Replan if</span>
              <span>{t}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const TRIAGE_COLORS: Record<number, { bg: string; text: string; border: string; dot: string }> = {
  1: { bg: "bg-red-500/10", text: "text-red-400", border: "border-red-500/30", dot: "bg-red-500" },
  2: { bg: "bg-orange-500/10", text: "text-orange-400", border: "border-orange-500/30", dot: "bg-orange-500" },
  3: { bg: "bg-yellow-500/8", text: "text-yellow-400", border: "border-yellow-500/25", dot: "bg-yellow-500" },
};

const RESPONSE_LABELS: Record<string, string> = {
  immediate_transport: "Immediate transport",
  "on-site stabilization": "On-site stabilization",
  on_site_stabilization: "On-site stabilization",
  "monitoring / delayed transport": "Monitoring / delayed transport",
  monitoring_delayed_transport: "Monitoring / delayed transport",
};

function TriagePrioritiesPanel({ priorities }: { priorities: TriagePriority[] }) {
  if (!priorities.length) return <p className="text-xs text-muted-foreground">No triage data.</p>;
  return (
    <div className="space-y-2">
      {priorities.map((t) => {
        const c = TRIAGE_COLORS[t.priority] ?? TRIAGE_COLORS[3];
        const rr = t.required_response?.trim();
        const responseDisplay = rr
          ? RESPONSE_LABELS[rr] ?? rr.replace(/_/g, " ")
          : null;
        return (
          <div key={t.priority} className={`p-3 rounded border ${c.border} ${c.bg}`}>
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className={`w-2 h-2 rounded-full shrink-0 ${c.dot}`} />
              <span className={`text-[10px] font-bold uppercase tracking-widest ${c.text}`}>
                Priority {t.priority}: {t.label}
              </span>
              <span className={`ml-auto text-sm font-bold ${c.text}`}>{t.estimated_count}</span>
              <span className={`text-[10px] ${c.text} opacity-70`}>est. patients</span>
            </div>
            {responseDisplay && (
              <p className={`text-[10px] font-semibold uppercase tracking-wide ${c.text} opacity-90 mb-1 ml-4`}>
                Required response: {responseDisplay}
              </p>
            )}
            <p className="text-xs text-foreground/75 ml-4">{t.required_action || t.required_response}</p>
          </div>
        );
      })}
    </div>
  );
}

function PatientTransportPanel({ transport, hospitals, primaryRoute, alternateRoute }: {
  transport: PatientTransport | null;
  hospitals?: { name: string; distance_mi?: number | null; trauma_level?: string | null }[];
  primaryRoute?: string | null;
  alternateRoute?: string | null;
}) {
  const t = transport ?? {
    primary_facilities: [] as string[],
    alternate_facilities: [] as string[],
    transport_routes: [] as string[],
    constraints: [] as string[],
    fallback_if_primary_unavailable: "",
  };
  const showArcgisRoutes = primaryRoute || alternateRoute;

  return (
    <div className="space-y-4">
      {t.primary_facilities.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Primary Receiving Facilities</p>
          <div className="space-y-1">
            {t.primary_facilities.map((f, i) => (
              <div key={i} className="flex gap-2 text-xs items-start">
                <span className="text-green-400/70 shrink-0">+</span>
                <span className="text-foreground/90">{f}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {t.alternate_facilities.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Alternate Receiving Facilities</p>
          <div className="space-y-1">
            {t.alternate_facilities.map((f, i) => (
              <div key={i} className="flex gap-2 text-xs items-start">
                <span className="text-muted-foreground/50 shrink-0">○</span>
                <span className="text-foreground/75">{f}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {t.transport_routes.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Recommended Transport Routes</p>
          <div className="space-y-1">
            {t.transport_routes.map((r, i) => (
              <div key={i} className="flex gap-2 text-xs items-start">
                <span className="text-blue-400/60 shrink-0">→</span>
                <span className="text-foreground/80">{r}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {showArcgisRoutes && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">ArcGIS Route Reference</p>
          {primaryRoute && (
            <div className="flex gap-2 text-xs text-foreground/80 mb-1">
              <span className="text-blue-400/60 shrink-0">P</span>
              <span>{primaryRoute}</span>
            </div>
          )}
          {alternateRoute && (
            <div className="flex gap-2 text-xs text-muted-foreground/90">
              <span className="text-muted-foreground/50 shrink-0">A</span>
              <span>Alternate: {alternateRoute}</span>
            </div>
          )}
        </div>
      )}

      {t.constraints.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Route Constraints</p>
          <div className="space-y-1">
            {t.constraints.map((c, i) => (
              <div key={i} className="flex gap-2 text-xs items-start">
                <span className="text-orange-400/70 shrink-0">⚠</span>
                <span className="text-foreground/80">{c}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {(t.fallback_if_primary_unavailable || alternateRoute) && (
        <div className="p-2.5 rounded border border-cyan-500/20 bg-cyan-500/5">
          <p className="text-[10px] font-bold text-cyan-400/90 uppercase tracking-widest mb-1">Fallback if Primary Route Unavailable</p>
          <p className="text-xs text-foreground/85">
            {t.fallback_if_primary_unavailable || alternateRoute || "Use alternate ArcGIS corridor and notify EMS command."}
          </p>
        </div>
      )}

      {hospitals && hospitals.length > 0 && (
        <div>
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1.5">Nearby Hospitals (ArcGIS)</p>
          <div className="space-y-1">
            {hospitals.map((h, i) => (
              <div key={i} className="flex gap-2 text-xs items-center">
                <span className="text-muted-foreground/40 shrink-0 w-4">{i + 1}.</span>
                <span className="flex-1 text-foreground/85">{h.name}</span>
                {h.trauma_level && (
                  <span className="text-[9px] text-blue-400/70 border border-blue-500/20 rounded px-1">Trauma {h.trauma_level}</span>
                )}
                {h.distance_mi != null && (
                  <span className="text-[10px] text-muted-foreground/50 shrink-0">{h.distance_mi} mi</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- main page ----

export default function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const updateRef = useRef<HTMLTextAreaElement>(null);

  const [incident, setIncident] = useState<Incident | null>(null);
  const [plan, setPlan] = useState<PlanVersion | null>(null);
  const [planVersions, setPlanVersions] = useState<PlanVersion[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [latestDiff, setLatestDiff] = useState<PlanDiff | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [replanning, setReplanning] = useState(false);
  const [error, setError] = useState("");
  const [updateText, setUpdateText] = useState("");
  const [viewVersion, setViewVersion] = useState<number | null>(null);
  const [activeRunVersion, setActiveRunVersion] = useState<number | null>(null);

  const mergePlanVersions = (incoming: PlanVersion[]) => {
    setPlanVersions((prev) => {
      const merged = [...prev];
      for (const version of incoming) {
        const existingIndex = merged.findIndex((item) => item.version === version.version);
        if (existingIndex >= 0) merged[existingIndex] = version;
        else merged.push(version);
      }
      merged.sort((a, b) => a.version - b.version);
      return merged;
    });
  };

  const refreshIncidentState = async (incidentId: string, selectedVersion?: number | null) => {
    const [live, versions] = await Promise.all([
      api.incidents.live(incidentId),
      api.plans.list(incidentId).catch(() => [] as PlanVersion[]),
    ]);
    const nextIncident = live.incident;
    const latestPlan = live.plan ?? null;

    setIncident(nextIncident);

    if (latestPlan) {
      mergePlanVersions([latestPlan]);
      setPlan((prev) => (prev && prev.version > latestPlan.version ? prev : latestPlan));
    }

    if (versions.length > 0) {
      mergePlanVersions(versions);
      const latest = versions[versions.length - 1];
      if (!latestPlan || latest.version >= latestPlan.version) {
        setPlan(latest);
      }
      if (selectedVersion == null || !versions.some((version) => version.version === selectedVersion)) {
        setViewVersion(latest.version);
      }
    } else if (latestPlan && selectedVersion == null) {
      setViewVersion(latestPlan.version);
    }

    const processing =
      nextIncident.status === "analyzing" ||
      nextIncident.status === "replanning" ||
      Boolean(latestPlan?.enrichment_pending);
    const targetVersion = processing
      ? (latestPlan?.version ?? nextIncident.current_plan_version) || undefined
      : (selectedVersion ?? latestPlan?.version ?? versions[versions.length - 1]?.version ?? nextIncident.current_plan_version) || undefined;

    if (processing) setActiveRunVersion(targetVersion ?? null);
    else setActiveRunVersion(null);

    if (processing) {
      setAgentRuns(live.agent_runs ?? []);
    } else if (targetVersion !== undefined && targetVersion > 0) {
      if (latestPlan && targetVersion === latestPlan.version) {
        setAgentRuns(live.agent_runs ?? []);
      } else {
        const runs = await api.agentRuns.list(incidentId, targetVersion).catch(() => [] as AgentRun[]);
        setAgentRuns(runs);
      }
    } else if (!processing) {
      setAgentRuns([]);
    }

    setAnalyzing(nextIncident.status === "analyzing");
    setReplanning(nextIncident.status === "replanning");

    return { incident: nextIncident, processing };
  };

  const syncIncidentState = useEffectEvent(async (incidentId: string, selectedVersion?: number | null) => {
    return refreshIncidentState(incidentId, selectedVersion);
  });

  const triggerAnalysis = useEffectEvent(async (inc: Incident) => {
    setAnalyzing(true);
    setReplanning(false);
    setError("");
    setActiveRunVersion(inc.current_plan_version + 1);
    setAgentRuns([]);
    setIncident({ ...inc, status: "analyzing" });
    void api.incidents.analyze(inc.id)
      .then((result) => {
        setIncident(result.incident);
        setPlan(result.plan);
        mergePlanVersions([result.plan]);
        setAgentRuns(result.agent_runs);
        setViewVersion(result.plan.version);
        setActiveRunVersion(result.plan.enrichment_pending ? result.plan.version : null);
        setAnalyzing(false);
      })
      .catch(async (err) => {
        setError(String(err));
        setAnalyzing(false);
        setActiveRunVersion(null);
        try {
          await refreshIncidentState(inc.id, viewVersion);
        } catch {
          // Keep the surfaced error; polling state is best-effort here.
        }
      });
  });

  const handleReplan = async () => {
    if (!incident || !updateText.trim()) return;
    const update = updateText.trim();
    setReplanning(true);
    setAnalyzing(false);
    setError("");
    setLatestDiff(null);
    setUpdateText("");
    setActiveRunVersion(incident.current_plan_version + 1);
    setIncident({ ...incident, status: "replanning" });

    void api.incidents.replan(incident.id, update)
      .then((result) => {
        setIncident(result.incident);
        setPlan(result.plan);
        mergePlanVersions([result.plan]);
        setAgentRuns(result.agent_runs);
        setViewVersion(result.plan.version);
        setLatestDiff(result.diff);
        setActiveRunVersion(result.plan.enrichment_pending ? result.plan.version : null);
        setReplanning(false);
      })
      .catch(async (err) => {
        setError(String(err));
        setReplanning(false);
        setActiveRunVersion(null);
        try {
          await refreshIncidentState(incident.id, viewVersion);
        } catch {
          // Keep the surfaced error; polling state is best-effort here.
        }
      });
  };

  const handleVersionSelect = (version: number) => {
    if (analyzing || replanning) return;
    setViewVersion(version); setLatestDiff(null);
    api.agentRuns.list(id, version).then(setAgentRuns).catch(() => {});
  };

  const redirectHome = useEffectEvent(() => {
    router.push("/");
  });

  const incidentId = incident?.id;
  const incidentStatus = incident?.status;

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    const load = async () => {
      try {
        const [live, versions] = await Promise.all([
          api.incidents.live(id),
          api.plans.list(id).catch(() => [] as PlanVersion[]),
        ]);
        const inc = live.incident;
        if (cancelled) return;
        setIncident(inc);
        if (live.plan) {
          mergePlanVersions([live.plan]);
          setPlan(live.plan);
        }
        if (versions.length > 0) {
          mergePlanVersions(versions);
          const latest = versions[versions.length - 1];
          setPlan(latest);
          setViewVersion(live.plan?.version ?? latest.version);
          const historyVersion =
            inc.status === "analyzing" || inc.status === "replanning" || live.plan?.enrichment_pending
              ? (live.plan?.version ?? inc.current_plan_version)
              : latest.version;
          const runs =
            live.plan && historyVersion === live.plan.version
              ? live.agent_runs
              : await api.agentRuns.list(id, historyVersion).catch(() => [] as AgentRun[]);
          if (!cancelled) setAgentRuns(runs);
        } else if (live.plan) {
          setViewVersion(live.plan.version);
          setAgentRuns(live.agent_runs);
        }
        if (cancelled) return;
        setAnalyzing(inc.status === "analyzing");
        setReplanning(inc.status === "replanning");
        setActiveRunVersion(
          inc.status === "analyzing" || inc.status === "replanning" || live.plan?.enrichment_pending
            ? (live.plan?.version ?? inc.current_plan_version)
            : null,
        );
        if (!cancelled && inc.status === "pending" && !live.plan) triggerAnalysis(inc);
      } catch {
        if (!cancelled) redirectHome();
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!incidentId) return;
    const latestKnownPlan = planVersions[planVersions.length - 1] ?? plan;
    const enrichmentPending = latestKnownPlan?.enrichment_pending ?? false;
    if (!(analyzing || replanning || incidentStatus === "analyzing" || incidentStatus === "replanning" || enrichmentPending)) {
      return;
    }

    let cancelled = false;
    let timeoutId: number | undefined;

    const tick = async () => {
      if (cancelled) return;
      try {
        const { processing } = await syncIncidentState(incidentId, viewVersion);
        if (!processing || cancelled) return;
      } catch {
        if (cancelled) return;
      }
      timeoutId = window.setTimeout(tick, 3500);
    };

    void tick();

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [incidentId, incidentStatus, analyzing, replanning, viewVersion, planVersions, plan]);

  if (!incident) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const isProcessing = analyzing || replanning || Boolean((planVersions[planVersions.length - 1] ?? plan)?.enrichment_pending);
  const committedDisplayPlan = planVersions.find((v) => v.version === viewVersion) ?? plan;
  const liveDraftPlan = incident
    ? buildLiveDraftPlan(incident, agentRuns, committedDisplayPlan ?? null, activeRunVersion)
    : null;
  const displayPlan = isProcessing ? liveDraftPlan ?? committedDisplayPlan : committedDisplayPlan;
  const isLatest = viewVersion === plan?.version;
  const activeDiff = isLatest ? latestDiff : null;
  const alertCount = displayPlan?.external_context?.alert_count ?? 0;
  const ext = displayPlan?.external_context;
  const flow = displayPlan ? derivePatientFlow(displayPlan) : null;
  const bottlenecks = displayPlan ? deriveBottlenecks(displayPlan, flow) : [];
  const primaryActions = displayPlan ? derivePrimaryActions(displayPlan) : [];

  return (
    <div className="command-page min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="print-hide border-b border-border bg-card/60 sticky top-0 z-20 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:px-6 lg:px-8 flex items-center gap-3">
          <button
            onClick={() => router.push("/")}
            className="text-muted-foreground hover:text-foreground text-xs transition-colors"
          >
            ← Unilert
          </button>
          <div className="w-px h-3 bg-border" />
          <span className="text-xs text-muted-foreground truncate flex-1">{incident.incident_type}</span>
          {isProcessing && (
            <div className="w-3.5 h-3.5 border border-primary border-t-transparent rounded-full animate-spin shrink-0" />
          )}
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto w-full px-4 py-5 sm:px-6 lg:px-8 lg:py-6 space-y-5">
        {error && (
          <div className="print-card rounded-2xl border border-red-500/30 bg-red-500/8 px-4 py-3 text-xs text-red-400">
            {error}
          </div>
        )}

        {/* Generating state */}
        {isProcessing && !displayPlan && (
          <div className="print-card rounded-3xl border border-border bg-card/80 p-8 text-center space-y-3">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-foreground font-medium">
              {replanning ? "Revising coordination plan live…" : "Building live coordination view…"}
            </p>
            <p className="text-[11px] text-muted-foreground">
              Situation → Intelligence → Patient Flow → Communications
            </p>
          </div>
        )}

        {/* Replanning notice */}
        {isProcessing && plan && (
          <div className="print-card flex items-center gap-2 rounded-2xl border border-primary/20 bg-primary/5 px-4 py-2.5 text-xs text-primary">
            <div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin shrink-0" />
            {displayPlan?.enrichment_pending
              ? "Initial decision surface is live. Swarm enrichment is updating in the background…"
              : replanning
              ? "Revising coordination plan based on field update…"
              : "Building live coordination view…"}
          </div>
        )}

        {displayPlan && (
          <>
            <section className="grid gap-5 xl:grid-cols-[1.45fr,0.95fr]">
              <DecisionSummaryCard
                incident={incident}
                plan={displayPlan}
                alertCount={alertCount}
                flow={flow}
                bottlenecks={bottlenecks}
                runs={agentRuns}
              />
              <WhatChangedCard
                plan={displayPlan}
                diff={activeDiff}
                runs={agentRuns}
                bottlenecks={bottlenecks}
              />
            </section>

            <OperationalStatusCard plan={displayPlan} />

            <section className="grid gap-5 xl:grid-cols-[0.92fr,1.08fr]">
              <PatientFlowOverviewCard flow={flow} />
              <FacilityAssignmentsCard plan={displayPlan} flow={flow} />
            </section>

            <section className="grid gap-5 xl:grid-cols-[0.95fr,1.05fr]">
              <BottlenecksCard bottlenecks={bottlenecks} />
              <ImmediateActionsCard actions={primaryActions} diff={activeDiff} />
            </section>

            <section className="space-y-3">
              {(displayPlan.decision_points?.length > 0 || displayPlan.tradeoffs?.length > 0 || activeDiff) && (
                <Accordion title="Decision Detail">
                  <div className="space-y-5">
                    {activeDiff && (
                      <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3">
                        <DiffSummary diff={activeDiff} />
                      </div>
                    )}
                    {displayPlan.decision_points?.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                          Coordination Decisions
                        </p>
                        <DecisionPointsPanel points={displayPlan.decision_points} />
                      </div>
                    )}
                    {displayPlan.tradeoffs?.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                          Decision Tradeoffs
                        </p>
                        <TradeoffsPanel tradeoffs={displayPlan.tradeoffs} />
                      </div>
                    )}
                  </div>
                </Accordion>
              )}

              {(displayPlan.command_recommendations ||
                displayPlan.command_transfer_summary ||
                Object.keys(displayPlan.owned_actions ?? {}).length > 0) && (
                <Accordion title="ICS Command">
                  <ICSCommandPanel
                    command={displayPlan.command_recommendations}
                    ownedActions={displayPlan.owned_actions}
                    transfer={displayPlan.command_transfer_summary}
                  />
                </Accordion>
              )}

              <Accordion
                title="Operational Detail"
                badge={
                  alertCount > 0 ? (
                    <span className="text-[10px] text-orange-400">
                      {alertCount} NWS alert{alertCount > 1 ? "s" : ""}
                    </span>
                  ) : undefined
                }
              >
                <div className="space-y-5">
                  {displayPlan.operational_priorities.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                        Operational Priorities
                      </p>
                      <OperationalPriorities priorities={displayPlan.operational_priorities} />
                    </div>
                  )}

                  {(displayPlan.incident_objectives?.length ?? 0) > 0 && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                        Incident Objectives
                      </p>
                      <IncidentObjectives objectives={displayPlan.incident_objectives} />
                    </div>
                  )}

                  <div className="space-y-2">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                      Execution Plan
                    </p>
                    <ExecutionPlan plan={displayPlan} diff={activeDiff} />
                  </div>

                  {(displayPlan.patient_transport != null || (ext?.hospitals && ext.hospitals.length > 0)) && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                        Transport & Routing
                      </p>
                      <PatientTransportPanel
                        transport={displayPlan.patient_transport ?? null}
                        hospitals={ext?.hospitals}
                        primaryRoute={ext?.primary_access_route ?? undefined}
                        alternateRoute={ext?.alternate_access_route ?? undefined}
                      />
                    </div>
                  )}

                  <div className="space-y-2">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                      Resource Assignments
                    </p>
                    <ResourceAssignments
                      assignments={displayPlan.resource_assignments}
                      roleAssignments={displayPlan.role_assignments}
                    />
                  </div>

                  {displayPlan.safety_considerations.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                        Safety Considerations
                      </p>
                      <SafetyConsiderations items={displayPlan.safety_considerations} />
                    </div>
                  )}
                </div>
              </Accordion>

              {(displayPlan.risk_notes.length > 0 ||
                (ext?.healthcare_risks && ext.healthcare_risks.length > 0) ||
                (ext?.replan_triggers && ext.replan_triggers.length > 0)) && (
                <Accordion title="Threat Analysis">
                  <ThreatAnalysisPanel
                    primaryRisks={displayPlan.risk_notes}
                    healthcareRisks={ext?.healthcare_risks ?? []}
                    replanTriggers={ext?.replan_triggers ?? []}
                    weatherThreats={ext?.weather_driven_threats ?? []}
                  />
                </Accordion>
              )}

              {((displayPlan.triage_priorities?.length ?? 0) > 0 || displayPlan.medical_impact) && (
                <Accordion title="Clinical Detail">
                  <div className="space-y-5">
                    {(displayPlan.triage_priorities?.length ?? 0) > 0 && (
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                          Triage Priorities
                        </p>
                        <TriagePrioritiesPanel priorities={displayPlan.triage_priorities} />
                      </div>
                    )}
                    {displayPlan.medical_impact && (
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                          Medical Impact
                        </p>
                        <MedicalImpactPanel impact={displayPlan.medical_impact} />
                      </div>
                    )}
                  </div>
                </Accordion>
              )}

              <Accordion title="Communications Plan">
                <CommsSummary plan={displayPlan} />
              </Accordion>

              <Accordion title="Situation Status">
                <SituationStatus plan={displayPlan} />
              </Accordion>

              {ext && (
                <Accordion title="Live Data Sources">
                  <ExternalContextPanel ctx={ext} />
                </Accordion>
              )}

              {((displayPlan.incident_log?.length ?? 0) > 0 || (incident.incident_log?.length ?? 0) > 0) && (
                <Accordion title="Incident Log">
                  <IncidentLogPanel entries={displayPlan.incident_log?.length ? displayPlan.incident_log : incident.incident_log ?? []} />
                </Accordion>
              )}

              {planVersions.length > 1 && (
                <Accordion title={`Plan History (${planVersions.length} versions)`}>
                  <PlanVersionHistory
                    versions={planVersions}
                    currentVersion={viewVersion ?? plan?.version ?? 1}
                    onSelect={handleVersionSelect}
                  />
                </Accordion>
              )}

              <SystemActivity runs={agentRuns} isLoading={isProcessing} />
            </section>
          </>
        )}

        <div className="h-28 print:hidden" />
      </main>

      {/* Field Update bar */}
        {displayPlan && (
          <div className="print-hide sticky bottom-0 z-20 border-t border-border bg-background/98 backdrop-blur-sm">
          <div className="max-w-7xl mx-auto px-4 py-3 sm:px-6 lg:px-8 space-y-2">
            <div className="flex gap-2 flex-wrap">
              {QUICK_UPDATES.map((u, i) => (
                <button
                  key={i}
                  onClick={() => { setUpdateText(u); updateRef.current?.focus(); }}
                  className="text-[10px] px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors"
                >
                  {u.slice(0, 35)}…
                </button>
              ))}
            </div>
            <div className="flex gap-2 items-end">
              <textarea
                ref={updateRef}
                value={updateText}
                onChange={(e) => setUpdateText(e.target.value)}
                rows={2}
                placeholder="Report field update — IAP will be revised automatically…"
                disabled={isProcessing}
                className="flex-1 px-3 py-2 rounded border border-border bg-input text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleReplan(); }}
              />
              <Button
                onClick={handleReplan}
                disabled={isProcessing || !updateText.trim()}
                className="h-[60px] px-4 bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-semibold shrink-0"
              >
                {replanning
                  ? <span className="flex items-center gap-1.5"><div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />Revising…</span>
                  : <span>Update &<br />Revise Plan</span>
                }
              </Button>
            </div>
          </div>
        </div>
      )}

      <footer className="print-hide border-t border-border max-w-7xl mx-auto w-full px-4 py-2 sm:px-6 lg:px-8">
        <p className="text-[10px] text-muted-foreground/50 text-center">
          Unilert · EMS & hospital coordination decision-support · Human review required before action
        </p>
      </footer>
    </div>
  );
}
