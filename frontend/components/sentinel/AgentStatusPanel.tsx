"use client";
import { Card, CardContent } from "@/components/ui/card";
import type { AgentRun } from "@/lib/api";

// --- Operational identity for each unit ---

const UNITS: Record<string, {
  role: string;
  mission: string;
  impact: string;
  deliverables: string[];
  completedNote: string;
}> = {
  incident_parser: {
    role: "Situation Unit",
    mission: "Establishes a verified, shared picture of the incident.",
    impact: "Ensures every responder is working from the same facts.",
    deliverables: ["Incident Brief", "Known Facts", "Critical Unknowns"],
    completedNote: "Incident brief produced",
  },
  risk_assessor: {
    role: "Threat Analysis Unit",
    mission: "Identifies the most dangerous aspects and potential escalation paths.",
    impact: "Tells the team what could go wrong before it does.",
    deliverables: ["Priority Threats", "Escalation Watchlist", "Replan Triggers"],
    completedNote: "Priority threats identified",
  },
  action_planner: {
    role: "Operations Planner",
    mission: "Defines what responders must do, who owns each action, and when.",
    impact: "Turns threat data into a concrete, time-phased response.",
    deliverables: ["Immediate Action Plan (0–10 min)", "30-Minute Plan", "2-Hour Plan", "Role Assignments"],
    completedNote: "Response plan generated",
  },
  communications: {
    role: "Communications Officer",
    mission: "Ensures the right people receive clear, actionable instructions.",
    impact: "Prevents confusion across responders, leadership, and the public.",
    deliverables: ["Responder Brief", "Leadership Update", "Public Advisory"],
    completedNote: "Alerts drafted",
  },
};

const AGENT_ORDER = ["incident_parser", "risk_assessor", "action_planner", "communications"];

function statusColor(status: string) {
  if (status === "completed") return "text-green-400";
  if (status === "running") return "text-cyan-400";
  if (status === "failed") return "text-red-400";
  return "text-muted-foreground";
}

function StatusDot({ status }: { status: string }) {
  const base = "inline-block w-2 h-2 rounded-full shrink-0";
  if (status === "running") return <span className={`${base} bg-cyan-400 animate-pulse shadow-[0_0_6px_#22d3ee]`} />;
  if (status === "completed") return <span className={`${base} bg-green-400`} />;
  if (status === "failed") return <span className={`${base} bg-red-400`} />;
  return <span className={`${base} bg-slate-600`} />;
}

function UnitCard({ agentType, run }: { agentType: string; run?: AgentRun }) {
  const unit = UNITS[agentType];
  const status = run?.status ?? "pending";
  const isActive = status === "running";
  const isDone = status === "completed";
  const isFailed = status === "failed";

  const duration =
    run?.started_at && run?.completed_at
      ? `${((new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000).toFixed(1)}s`
      : null;

  return (
    <div
      className={`rounded border p-3 space-y-2 transition-all ${
        isActive
          ? "border-cyan-500/50 bg-cyan-500/5"
          : isDone
          ? "border-green-500/20 bg-green-500/5"
          : isFailed
          ? "border-red-500/30 bg-red-500/5"
          : "border-border bg-card/30"
      }`}
    >
      {/* Header row */}
      <div className="flex items-center gap-2">
        <StatusDot status={status} />
        <span className={`text-xs font-semibold ${isDone ? "text-foreground" : isActive ? "text-cyan-300" : "text-muted-foreground"}`}>
          {unit.role}
        </span>
        {isDone && (
          <span className="ml-auto text-[10px] text-green-400">{unit.completedNote}</span>
        )}
        {isActive && (
          <span className="ml-auto text-[10px] text-cyan-400 animate-pulse">Working…</span>
        )}
        {isFailed && (
          <span className="ml-auto text-[10px] text-red-400">Failed</span>
        )}
        {duration && (
          <span className="text-[10px] text-muted-foreground ml-1">{duration}</span>
        )}
      </div>

      {/* Deliverables — only show when done or active */}
      {(isDone || isActive) && (
        <div className="space-y-1">
          <p className="text-[10px] text-muted-foreground uppercase tracking-widest">Deliverables</p>
          <ul className="space-y-0.5">
            {unit.deliverables.map((d) => (
              <li key={d} className="flex items-center gap-1.5 text-[10px]">
                {isDone
                  ? <span className="text-green-400">✓</span>
                  : <span className="text-cyan-400/60 animate-pulse">◌</span>
                }
                <span className={isDone ? "text-foreground/80" : "text-muted-foreground"}>{d}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Impact line — only when done */}
      {isDone && (
        <p className="text-[10px] text-muted-foreground border-t border-border/50 pt-1.5 mt-1">
          {unit.impact}
        </p>
      )}

      {/* Error */}
      {isFailed && run?.error_message && (
        <p className="text-[10px] text-red-400 truncate">{run.error_message}</p>
      )}

      {/* Machine ID — subtle, for demo */}
      {run?.machine_id && (
        <p className="text-[10px] text-muted-foreground/40 font-mono">
          machine:{run.machine_id.slice(0, 12)}
        </p>
      )}
    </div>
  );
}

interface Props {
  runs: AgentRun[];
  isLoading?: boolean;
}

export function AgentStatusPanel({ runs, isLoading }: Props) {
  // Build a map from agent_type → run for easy lookup
  const runMap: Record<string, AgentRun> = {};
  for (const run of runs) runMap[run.agent_type] = run;

  const hasAnyActivity = runs.length > 0 || isLoading;
  if (!hasAnyActivity) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-semibold px-0.5 mb-2">
        Response Units
      </p>
      {AGENT_ORDER.map((type) => (
        <UnitCard key={type} agentType={type} run={runMap[type]} />
      ))}
    </div>
  );
}
