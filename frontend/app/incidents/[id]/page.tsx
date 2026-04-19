"use client";
import { useState, useEffect, use, useRef } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { SeverityBadge } from "@/components/sentinel/SeverityBadge";
import { PriorityActions } from "@/components/sentinel/PriorityActions";
import { SystemActivity } from "@/components/sentinel/SystemActivity";
import { Accordion } from "@/components/sentinel/Accordion";
import { CommunicationsPanel } from "@/components/sentinel/CommunicationsPanel";
import { PlanVersionHistory } from "@/components/sentinel/PlanVersionHistory";
import { ExternalContextPanel } from "@/components/sentinel/ExternalContextPanel";
import { api, type Incident, type PlanVersion, type AgentRun, type PlanDiff, type ActionItem, type MedicalImpact, type TriagePriority, type PatientTransport, type PatientFlowSummary, type FacilityAssignment, type DecisionPoint, type Tradeoff } from "@/lib/api";

const QUICK_UPDATES = [
  "Additional patients found — revise counts",
  "Primary route blocked — need alternate",
  "Receiving hospital at capacity — reroute",
  "Critical patient deteriorating — transport now",
  "Decon corridor established — update routing",
  "Hospital confirmed ready — update ETA",
];

// ---- IAP sub-components ----

function IncidentOverview({ incident, plan, alertCount }: {
  incident: Incident;
  plan: PlanVersion | null;
  alertCount: number;
}) {
  return (
    <div className="p-4 rounded-lg border border-border bg-card space-y-3">
      {/* Header row */}
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Incident Type</span>
            <SeverityBadge level={plan?.assessed_severity ?? incident.severity_hint} />
            {alertCount > 0 && (
              <span className="text-[10px] text-orange-400 border border-orange-500/30 rounded px-1.5 py-0.5">
                {alertCount} NWS Alert{alertCount > 1 ? "s" : ""}
              </span>
            )}
          </div>
          <p className="text-base font-semibold text-foreground">{incident.incident_type}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-[10px] text-muted-foreground uppercase tracking-widest">Initiated</p>
          <p className="text-xs text-foreground/70">{new Date(incident.created_at).toLocaleTimeString()}</p>
          {plan && (
            <p className="text-[10px] text-muted-foreground/50 mt-0.5">Plan v{plan.version}</p>
          )}
        </div>
      </div>

      {/* Location + period */}
      <div className="grid grid-cols-2 gap-3 pt-1 border-t border-border/50">
        <div>
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-0.5">Location</p>
          <p className="text-xs text-foreground/90">{incident.location}</p>
        </div>
        {plan?.operational_period && (
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-0.5">Operational Period</p>
            <p className="text-xs text-foreground/90">{plan.operational_period}</p>
          </div>
        )}
      </div>

      {/* Operational summary */}
      {plan?.incident_summary && (
        <p className="text-xs text-foreground/70 leading-relaxed border-t border-border/50 pt-2">
          {plan.incident_summary}
        </p>
      )}
    </div>
  );
}

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

function ExecutionPlan({ plan, diff }: { plan: PlanVersion; diff: PlanDiff | null }) {
  const added = new Set(diff?.added_actions.map((a) => a.description) ?? []);
  const removed = new Set(diff?.removed_actions.map((a) => a.description) ?? []);

  function Phase({ label, sublabel, items }: { label: string; sublabel: string; items: ActionItem[] }) {
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

  return (
    <div className="space-y-5">
      <Phase label="Immediate" sublabel="0–10 min" items={plan.immediate_actions} />
      <Phase label="Short-Term" sublabel="10–30 min" items={plan.short_term_actions} />
      <Phase label="Ongoing" sublabel="30–120 min" items={plan.ongoing_actions} />
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

function PatientFlowPanel({ flow }: { flow: PatientFlowSummary }) {
  const total = flow.total_incoming;
  return (
    <div className="p-4 rounded-lg border border-border bg-card space-y-4">
      <div className="flex items-baseline gap-2">
        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Patient Flow Overview</p>
        {total > 0 && <span className="text-xs text-muted-foreground">— {total} incoming</span>}
      </div>

      {total > 0 && (
        <div className="grid grid-cols-4 gap-2">
          <div className="p-2 rounded border border-border bg-card/60 text-center">
            <p className="text-xl font-bold text-foreground">{total}</p>
            <p className="text-[9px] text-muted-foreground uppercase tracking-widest">Total</p>
          </div>
          <div className="p-2 rounded border border-red-500/30 bg-red-500/8 text-center">
            <p className="text-xl font-bold text-red-400">{flow.critical}</p>
            <p className="text-[9px] text-red-400/70 uppercase tracking-widest">Critical</p>
          </div>
          <div className="p-2 rounded border border-orange-500/30 bg-orange-500/8 text-center">
            <p className="text-xl font-bold text-orange-400">{flow.moderate}</p>
            <p className="text-[9px] text-orange-400/70 uppercase tracking-widest">Moderate</p>
          </div>
          <div className="p-2 rounded border border-yellow-500/25 bg-yellow-500/5 text-center">
            <p className="text-xl font-bold text-yellow-400">{flow.minor}</p>
            <p className="text-[9px] text-yellow-400/70 uppercase tracking-widest">Minor</p>
          </div>
        </div>
      )}

      {flow.facility_assignments.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Facility Assignments</p>
          {flow.facility_assignments.map((fa, i) => {
            const s = STRAIN_STYLES[fa.capacity_strain] ?? STRAIN_STYLES.normal;
            return (
              <div key={i} className={`p-3 rounded border ${s.border} ${s.bg}`}>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.dot}`} />
                    <span className="text-xs font-semibold text-foreground truncate">{fa.hospital}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`text-[10px] font-bold ${s.text}`}>{fa.capacity_strain.toUpperCase()}</span>
                    <span className="text-sm font-bold text-foreground">{fa.patients_assigned} pts</span>
                  </div>
                </div>
                {fa.patient_types.length > 0 && (
                  <div className="flex gap-1 flex-wrap ml-3.5 mb-1">
                    {fa.patient_types.map((pt, j) => (
                      <span key={j} className="text-[9px] px-1.5 py-0.5 rounded border border-border text-muted-foreground/80">{pt}</span>
                    ))}
                  </div>
                )}
                {fa.routing_reason && <p className="text-[11px] text-foreground/60 ml-3.5">{fa.routing_reason}</p>}
                {fa.reroute_trigger && (
                  <p className="text-[10px] text-orange-400/70 ml-3.5 mt-0.5">Reroute if: {fa.reroute_trigger}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {flow.bottlenecks.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Active Bottlenecks</p>
          {flow.bottlenecks.map((b, i) => (
            <div key={i} className="flex gap-2 text-xs items-start">
              <span className="text-orange-400/70 shrink-0">⚠</span>
              <span className="text-foreground/80">{b}</span>
            </div>
          ))}
        </div>
      )}

      {flow.distribution_rationale && (
        <p className="text-[11px] text-muted-foreground/70 border-t border-border/50 pt-2">
          {flow.distribution_rationale}
        </p>
      )}
    </div>
  );
}

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

  useEffect(() => {
    if (!id) return;
    api.incidents.get(id).then((inc) => {
      setIncident(inc);
      if (inc.status === "pending") triggerAnalysis(inc);
      else if (inc.status === "analyzing") { setAnalyzing(true); pollUntilDone(inc.id); }
    }).catch(() => router.push("/"));
    api.plans.list(id).then((versions) => {
      if (versions.length > 0) {
        const latest = versions[versions.length - 1];
        setPlan(latest); setPlanVersions(versions); setViewVersion(latest.version);
        api.agentRuns.list(id).then(setAgentRuns).catch(() => {});
      }
    }).catch(() => {});
  }, [id]);

  const triggerAnalysis = async (inc: Incident) => {
    setAnalyzing(true); setError("");
    try {
      const result = await api.incidents.analyze(inc.id);
      setIncident(result.incident); setPlan(result.plan);
      setPlanVersions([result.plan]); setAgentRuns(result.agent_runs);
      setViewVersion(result.plan.version);
    } catch (err) { setError(String(err)); }
    finally { setAnalyzing(false); }
  };

  const pollUntilDone = async (incId: string) => {
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const versions = await api.plans.list(incId).catch(() => []);
      if (versions.length > 0) {
        const latest = versions[versions.length - 1];
        setPlan(latest); setPlanVersions(versions); setViewVersion(latest.version);
        setAnalyzing(false); return;
      }
    }
    setAnalyzing(false);
  };

  const handleReplan = async () => {
    if (!incident || !updateText.trim()) return;
    setReplanning(true); setError("");
    try {
      const result = await api.incidents.replan(incident.id, updateText.trim());
      setIncident(result.incident); setPlan(result.plan);
      setPlanVersions((prev) => [...prev, result.plan]);
      setAgentRuns(result.agent_runs); setViewVersion(result.plan.version);
      setLatestDiff(result.diff); setUpdateText("");
    } catch (err) { setError(String(err)); }
    finally { setReplanning(false); }
  };

  const handleVersionSelect = (version: number) => {
    setViewVersion(version); setLatestDiff(null);
    api.agentRuns.list(id, version).then(setAgentRuns).catch(() => {});
  };

  if (!incident) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const isProcessing = analyzing || replanning;
  const displayPlan = planVersions.find((v) => v.version === viewVersion) ?? plan;
  const isLatest = viewVersion === plan?.version;
  const activeDiff = isLatest ? latestDiff : null;
  const alertCount = displayPlan?.external_context?.alert_count ?? 0;
  const ext = displayPlan?.external_context;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b border-border bg-card/50 sticky top-0 z-20 backdrop-blur-sm">
        <div className="max-w-2xl mx-auto px-5 py-3 flex items-center gap-3">
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

      <main className="flex-1 max-w-2xl mx-auto w-full px-5 py-5 space-y-3">
        {error && (
          <div className="p-3 rounded border border-red-500/30 bg-red-500/8 text-red-400 text-xs">{error}</div>
        )}

        {/* Incident Overview */}
        <IncidentOverview incident={incident} plan={displayPlan ?? null} alertCount={alertCount} />

        {/* Generating state */}
        {isProcessing && !plan && (
          <div className="p-8 rounded-lg border border-border bg-card text-center space-y-3">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-foreground font-medium">
              {replanning ? "Revising coordination plan…" : "Generating coordination plan…"}
            </p>
            <p className="text-[11px] text-muted-foreground">
              Situation → Intelligence → Patient Flow → Communications
            </p>
          </div>
        )}

        {/* Replanning notice */}
        {isProcessing && plan && (
          <div className="flex items-center gap-2 px-4 py-2.5 rounded border border-primary/20 bg-primary/5 text-xs text-primary">
            <div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin shrink-0" />
            Revising coordination plan based on field update…
          </div>
        )}

        {/* What Changed (replan diff — most prominent) */}
        {activeDiff && (
          <div className="px-4 py-3 rounded border border-cyan-500/20 bg-cyan-500/5">
            <DiffSummary diff={activeDiff} />
          </div>
        )}

        {/* 1. PATIENT FLOW OVERVIEW — hero section */}
        {displayPlan?.patient_flow && (
          <PatientFlowPanel flow={displayPlan.patient_flow} />
        )}

        {/* 2. TRIAGE PRIORITIES */}
        {displayPlan?.triage_priorities && displayPlan.triage_priorities.length > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest px-0.5">
              Triage Priorities
            </p>
            <TriagePrioritiesPanel priorities={displayPlan.triage_priorities} />
          </div>
        )}

        {/* 3. IMMEDIATE ACTIONS */}
        {displayPlan && displayPlan.immediate_actions.length > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest px-0.5">
              Immediate Actions <span className="text-muted-foreground/40 font-normal normal-case tracking-normal">0–10 min</span>
            </p>
            <PriorityActions actions={displayPlan.immediate_actions} diff={activeDiff} />
          </div>
        )}

        {/* Agent status */}
        <SystemActivity runs={agentRuns} isLoading={isProcessing} />

        {/* Collapsible sections */}
        {displayPlan && (
          <>
            {/* Decision Points */}
            {displayPlan.decision_points?.length > 0 && (
              <Accordion title="Coordination Decisions" defaultOpen>
                <DecisionPointsPanel points={displayPlan.decision_points} />
              </Accordion>
            )}

            {/* Tradeoffs */}
            {displayPlan.tradeoffs?.length > 0 && (
              <Accordion title="Decision Tradeoffs">
                <TradeoffsPanel tradeoffs={displayPlan.tradeoffs} />
              </Accordion>
            )}

            {/* Incident Objectives */}
            {displayPlan.incident_objectives?.length > 0 && (
              <Accordion title="Incident Objectives">
                <IncidentObjectives objectives={displayPlan.incident_objectives} />
              </Accordion>
            )}

            {/* Operational Priorities */}
            <Accordion
              title="Operational Priorities"
              defaultOpen={["high", "critical"].includes(displayPlan.assessed_severity)}
              badge={
                alertCount > 0
                  ? <span className="text-[10px] text-orange-400">{alertCount} NWS alert{alertCount > 1 ? "s" : ""}</span>
                  : undefined
              }
            >
              <OperationalPriorities priorities={displayPlan.operational_priorities} />
            </Accordion>

            {/* Full Execution Plan */}
            <Accordion title="Execution Plan">
              <ExecutionPlan plan={displayPlan} diff={activeDiff} />
            </Accordion>

            {/* Threat Analysis */}
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

            {/* Patient Transport */}
            {(displayPlan.patient_transport != null || (ext?.hospitals && ext.hospitals.length > 0)) && (
              <Accordion title="Transport & Routing">
                <PatientTransportPanel
                  transport={displayPlan.patient_transport ?? null}
                  hospitals={ext?.hospitals}
                  primaryRoute={ext?.primary_access_route ?? undefined}
                  alternateRoute={ext?.alternate_access_route ?? undefined}
                />
              </Accordion>
            )}

            {/* Communications Plan */}
            <Accordion title="Communications Plan">
              <CommsSummary plan={displayPlan} />
            </Accordion>

            {/* Situation Status */}
            <Accordion title="Situation Status">
              <SituationStatus plan={displayPlan} />
            </Accordion>

            {/* Resource Assignments */}
            <Accordion title="Resource Assignments">
              <ResourceAssignments
                assignments={displayPlan.resource_assignments}
                roleAssignments={displayPlan.role_assignments}
              />
            </Accordion>

            {/* Safety */}
            {displayPlan.safety_considerations.length > 0 && (
              <Accordion title="Safety Considerations">
                <SafetyConsiderations items={displayPlan.safety_considerations} />
              </Accordion>
            )}

            {/* Live data */}
            {ext && (
              <Accordion title="Live Data Sources">
                <ExternalContextPanel ctx={ext} />
              </Accordion>
            )}

            {/* Plan history */}
            {planVersions.length > 1 && (
              <Accordion title={`Plan History (${planVersions.length} versions)`}>
                <PlanVersionHistory
                  versions={planVersions}
                  currentVersion={viewVersion ?? plan?.version ?? 1}
                  onSelect={handleVersionSelect}
                />
              </Accordion>
            )}
          </>
        )}

        <div className="h-36" />
      </main>

      {/* Field Update bar */}
      {plan && (
        <div className="sticky bottom-0 z-20 border-t border-border bg-background/98 backdrop-blur-sm">
          <div className="max-w-2xl mx-auto px-5 py-3 space-y-2">
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

      <footer className="border-t border-border max-w-2xl mx-auto w-full px-5 py-2">
        <p className="text-[10px] text-muted-foreground/50 text-center">
          Unilert · EMS & hospital coordination decision-support · Human review required before action
        </p>
      </footer>
    </div>
  );
}
