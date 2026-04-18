"use client";
import type { IncidentStatus } from "@/lib/api";

const config: Record<string, { color: string; label: string }> = {
  pending:    { color: "text-slate-400", label: "PENDING" },
  analyzing:  { color: "text-cyan-400",  label: "ANALYZING" },
  active:     { color: "text-green-400", label: "ACTIVE" },
  replanning: { color: "text-yellow-400",label: "REPLANNING" },
  resolved:   { color: "text-slate-500", label: "RESOLVED" },
};

export function StatusBadge({ status }: { status: IncidentStatus | string }) {
  const c = config[status] ?? config.pending;
  return (
    <span className={`text-xs font-mono font-semibold tracking-widest ${c.color}`}>
      ● {c.label}
    </span>
  );
}
