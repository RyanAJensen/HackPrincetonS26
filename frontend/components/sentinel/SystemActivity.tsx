"use client";
import { useState } from "react";
import type { AgentRun } from "@/lib/api";

const UNIT_LABELS: Record<string, string> = {
  incident_parser: "Situation Unit",
  risk_assessor:   "Threat Analysis",
  action_planner:  "Operations Planner",
  communications:  "Communications Officer",
};

const UNIT_VERBS: Record<string, string> = {
  incident_parser: "brief produced",
  risk_assessor:   "threats identified",
  action_planner:  "plan generated",
  communications:  "alerts drafted",
};

interface Props {
  runs: AgentRun[];
  isLoading?: boolean;
}

export function SystemActivity({ runs, isLoading }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!isLoading && runs.length === 0) return null;

  const allDone = runs.length === 4 && runs.every((r) => r.status === "completed");
  const anyFailed = runs.some((r) => r.status === "failed");
  const runningRun = runs.find((r) => r.status === "running");

  const statusLabel = anyFailed
    ? "One unit encountered an error"
    : isLoading && !allDone
    ? runningRun
      ? `${UNIT_LABELS[runningRun.agent_type] ?? "Agent"} working…`
      : "Units initializing…"
    : "All units complete";

  return (
    <div className="border border-border rounded">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/3 transition-colors"
      >
        {/* Status dot */}
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${
            anyFailed
              ? "bg-red-400"
              : isLoading && !allDone
              ? "bg-cyan-400 animate-pulse"
              : "bg-green-400"
          }`}
        />
        <span className="text-[11px] text-muted-foreground flex-1 text-left">{statusLabel}</span>
        <span className="text-[10px] text-muted-foreground/50">{expanded ? "Hide" : "Details"}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-3 pt-1 border-t border-border space-y-1">
          {(["incident_parser", "risk_assessor", "action_planner", "communications"] as const).map((type) => {
            const run = runs.find((r) => r.agent_type === type);
            const status = run?.status ?? (isLoading ? "pending" : "pending");
            const duration = run?.started_at && run?.completed_at
              ? `${((new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000).toFixed(1)}s`
              : null;
            return (
              <div key={type} className="flex items-center gap-2 text-[11px]">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 inline-block ${
                  status === "completed" ? "bg-green-400"
                  : status === "running"   ? "bg-cyan-400 animate-pulse"
                  : status === "failed"    ? "bg-red-400"
                  : "bg-border"
                }`} />
                <span className="text-muted-foreground/70">{UNIT_LABELS[type]}</span>
                {status === "completed" && (
                  <span className="text-muted-foreground/40">— {UNIT_VERBS[type]}{duration ? ` (${duration})` : ""}</span>
                )}
                {status === "running" && (
                  <span className="text-cyan-400/70">— working…</span>
                )}
                {status === "failed" && (
                  <span className="text-red-400/70">— failed</span>
                )}
                {run?.machine_id && (
                  <span className="ml-auto text-[9px] text-muted-foreground/25 font-mono">{run.machine_id.slice(0, 10)}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
