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
  incident_parser: "medical impact estimated",
  risk_assessor:   "healthcare risks analyzed",
  action_planner:  "EMS & transport plan ready",
  communications:  "EMS / hospital comms drafted",
};

const RUNTIME_BADGE: Record<string, { label: string; classes: string }> = {
  dedalus: {
    label: "DedalusRunner",
    classes: "text-cyan-400 border-cyan-500/30 bg-cyan-500/8",
  },
  dedalus_degraded: {
    label: "Dedalus (legacy)",
    classes: "text-orange-400 border-orange-500/30 bg-orange-500/8",
  },
  local: {
    label: "Local K2",
    classes: "text-muted-foreground/60 border-border",
  },
};

function RuntimeBadge({ runtime }: { runtime?: string }) {
  const r = runtime ?? "local";
  const badge = RUNTIME_BADGE[r] ?? RUNTIME_BADGE.local;
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded border font-mono ${badge.classes}`}>
      {badge.label}
    </span>
  );
}

function MachineTag({ machineId, runtime }: { machineId?: string; runtime?: string }) {
  if (!machineId) return null;
  const isDedalus = runtime === "dedalus" || runtime === "dedalus_degraded";
  return (
    <span className={`text-[9px] font-mono ${isDedalus ? "text-cyan-400/50" : "text-muted-foreground/25"}`}>
      {machineId.slice(0, 12)}
    </span>
  );
}

interface Props {
  runs: AgentRun[];
  isLoading?: boolean;
}

export function SystemActivity({ runs, isLoading }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [logsFor, setLogsFor] = useState<string | null>(null);

  if (!isLoading && runs.length === 0) return null;

  const allDone = runs.length === 4 && runs.every((r) => r.status === "completed");
  const anyFailed = runs.some((r) => r.status === "failed");
  const runningRun = runs.find((r) => r.status === "running");

  // Determine if Dedalus is actively being used
  const dedalusRuns = runs.filter((r) => r.runtime === "dedalus" || r.runtime === "dedalus_degraded");
  const hasDedalus = dedalusRuns.length > 0;

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

        {hasDedalus && (
          <span className="text-[9px] font-mono text-cyan-400/60 hidden sm:block">
            DedalusRunner
          </span>
        )}
        {!hasDedalus && runs.length > 0 && (
          <span className="text-[9px] text-muted-foreground/40">local runtime</span>
        )}

        <span className="text-[10px] text-muted-foreground/50">{expanded ? "Hide" : "Details"}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-3 pt-1 border-t border-border space-y-2">

          {hasDedalus && (() => {
            const isHealthy = dedalusRuns.some((r) => r.runtime === "dedalus");
            const isLegacyDegraded = !isHealthy && dedalusRuns.some((r) => r.runtime === "dedalus_degraded");
            return (
              <div className={`rounded border px-3 py-2 space-y-1 ${isHealthy ? "border-cyan-500/20 bg-cyan-500/5" : "border-orange-500/20 bg-orange-500/5"}`}>
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full inline-block shrink-0 ${isHealthy ? "bg-cyan-400 animate-pulse" : "bg-orange-400"}`} />
                  <span className={`text-[10px] font-semibold ${isHealthy ? "text-cyan-400" : "text-orange-400"}`}>
                    {isHealthy ? "DedalusRunner active" : isLegacyDegraded ? "Legacy degraded run" : "Dedalus"}
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground/60">
                  {isHealthy
                    ? "Agents use dedalus_labs.DedalusRunner — structured output from result.final_output (no machine mounts)."
                    : "Older plan may show degraded machine mode; new runs use DedalusRunner only."}
                </p>
              </div>
            );
          })()}

          {/* Per-unit rows */}
          {(["incident_parser", "risk_assessor", "action_planner", "communications"] as const).map((type) => {
            const run = runs.find((r) => r.agent_type === type);
            const status = run?.status ?? (isLoading ? "pending" : "pending");
            const duration = run?.started_at && run?.completed_at
              ? `${((new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000).toFixed(1)}s`
              : null;
            const showingLogs = logsFor === type && run?.log_entries?.length;

            return (
              <div key={type} className="space-y-1">
                <div className="flex items-center gap-2 text-[11px]">
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
                    <span className="text-cyan-400/70">— executing…</span>
                  )}
                  {status === "failed" && (
                    <span className="text-red-400/70">— failed</span>
                  )}

                  <div className="ml-auto flex items-center gap-1.5">
                    {run && <RuntimeBadge runtime={run.runtime} />}
                    <MachineTag machineId={run?.machine_id} runtime={run?.runtime} />
                    {run?.log_entries?.length ? (
                      <button
                        onClick={() => setLogsFor(showingLogs ? null : type)}
                        className="text-[9px] text-muted-foreground/40 hover:text-muted-foreground/70 transition-colors"
                      >
                        {showingLogs ? "hide" : "logs"}
                      </button>
                    ) : null}
                  </div>
                </div>

                {/* Error message */}
                {status === "failed" && run?.error_message && (
                  <div className="ml-3.5 text-[9px] font-mono text-red-400/70 break-all border-l border-red-500/30 pl-2">
                    {run.error_message}
                  </div>
                )}

                {/* Log entries */}
                {showingLogs && run?.log_entries && (
                  <div className="ml-4 pl-2 border-l border-border/50 space-y-0.5">
                    {run.log_entries.map((entry, i) => (
                      <p key={i} className="text-[9px] font-mono text-muted-foreground/50 leading-relaxed">
                        {entry}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
