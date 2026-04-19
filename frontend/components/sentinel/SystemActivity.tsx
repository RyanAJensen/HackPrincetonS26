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
  swarm: {
    label: "Dedalus Machines",
    classes: "text-cyan-300 border-cyan-500/30 bg-cyan-500/10",
  },
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

function latestRunByType(runs: AgentRun[], agentType: string) {
  return [...runs].reverse().find((run) => run.agent_type === agentType);
}

function hasUsableOutput(run?: AgentRun | null) {
  return Boolean(run?.output_artifact && Object.keys(run.output_artifact).length > 0);
}

function isActuallyUnavailable(run?: AgentRun | null) {
  if (!run || run.status !== "failed") return false;
  if (run.fallback_used && hasUsableOutput(run)) return false;
  return !hasUsableOutput(run);
}

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
  const isDedalus = runtime === "dedalus" || runtime === "dedalus_degraded" || runtime === "swarm";
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

  const blockingFailures = runs.filter((r) => isActuallyUnavailable(r));
  const degradedRuns = runs.filter((r) => r.degraded || r.fallback_used);
  const allDone = runs.length === 4 && runs.every((r) => r.status === "completed" || r.fallback_used);
  const anyFailed = blockingFailures.length > 0;
  const runningRun = runs.find((r) => r.status === "running");

  // Determine if Dedalus is actively being used
  const dedalusRuns = runs.filter((r) => r.runtime === "dedalus" || r.runtime === "dedalus_degraded" || r.runtime === "swarm");
  const hasDedalus = dedalusRuns.length > 0;

  const statusLabel = anyFailed
    ? "One unit encountered an error"
    : degradedRuns.length > 0 && !isLoading
    ? `${degradedRuns.length} unit${degradedRuns.length > 1 ? "s" : ""} in fallback mode`
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
            {dedalusRuns.some((r) => r.runtime === "swarm") ? "Dedalus Machines" : "DedalusRunner"}
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
            const usesMachines = dedalusRuns.some((r) => r.runtime === "swarm");
            const isHealthy = usesMachines || dedalusRuns.some((r) => r.runtime === "dedalus");
            const isLegacyDegraded = !isHealthy && dedalusRuns.some((r) => r.runtime === "dedalus_degraded");
            return (
              <div className={`rounded border px-3 py-2 space-y-1 ${isHealthy ? "border-cyan-500/20 bg-cyan-500/5" : "border-orange-500/20 bg-orange-500/5"}`}>
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full inline-block shrink-0 ${isHealthy ? "bg-cyan-400 animate-pulse" : "bg-orange-400"}`} />
                  <span className={`text-[10px] font-semibold ${isHealthy ? "text-cyan-400" : "text-orange-400"}`}>
                    {usesMachines ? "Dedalus Machines active" : isHealthy ? "DedalusRunner active" : isLegacyDegraded ? "Legacy degraded run" : "Dedalus"}
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground/60">
                  {usesMachines
                    ? "Agents are enriching the plan on remote Dedalus Machines while the local first answer stays active."
                    : isHealthy
                    ? "Agents use dedalus_labs.DedalusRunner — structured output from result.final_output."
                    : "Older plan may show degraded machine mode; new runs use DedalusRunner only."}
                </p>
              </div>
            );
          })()}

          {/* Per-unit rows */}
          {(["incident_parser", "risk_assessor", "action_planner", "communications"] as const).map((type) => {
            const run = latestRunByType(runs, type);
            const status = run?.status ?? (isLoading ? "pending" : "pending");
            const degraded = Boolean(run?.degraded || run?.fallback_used);
            const duration = run?.started_at && run?.completed_at
              ? `${((new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000).toFixed(1)}s`
              : null;
            const showingLogs = logsFor === type && run?.log_entries?.length;

            return (
              <div key={type} className="space-y-1">
                <div className="flex items-center gap-2 text-[11px]">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 inline-block ${
                    degraded ? "bg-amber-400"
                    : status === "completed" ? "bg-green-400"
                    : status === "running"   ? "bg-cyan-400 animate-pulse"
                    : status === "failed"    ? "bg-red-400"
                    : "bg-border"
                  }`} />
                  <span className="text-muted-foreground/70">{UNIT_LABELS[type]}</span>

                  {degraded && (
                    <span className="text-amber-400/80">
                      — {hasUsableOutput(run) ? "local fallback active" : "fallback pending"}
                      {duration ? ` (${duration})` : ""}
                    </span>
                  )}
                  {!degraded && status === "completed" && (
                    <span className="text-muted-foreground/40">— {UNIT_VERBS[type]}{duration ? ` (${duration})` : ""}</span>
                  )}
                  {!degraded && status === "running" && (
                    <span className="text-cyan-400/70">— executing…</span>
                  )}
                  {!degraded && status === "failed" && (
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
                  <div className={`ml-3.5 break-all border-l pl-2 text-[9px] font-mono ${
                    degraded && hasUsableOutput(run)
                      ? "border-amber-500/30 text-amber-300/80"
                      : "border-red-500/30 text-red-400/70"
                  }`}>
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
