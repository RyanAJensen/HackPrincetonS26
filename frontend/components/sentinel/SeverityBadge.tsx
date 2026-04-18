"use client";
import { Badge } from "@/components/ui/badge";
import type { SeverityLevel } from "@/lib/api";

const colors: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400 border-red-500/50",
  high: "bg-orange-500/20 text-orange-400 border-orange-500/50",
  medium: "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",
  low: "bg-green-500/20 text-green-400 border-green-500/50",
  unknown: "bg-slate-500/20 text-slate-400 border-slate-500/50",
};

export function SeverityBadge({ level }: { level?: string }) {
  const key = level?.toLowerCase() ?? "unknown";
  return (
    <Badge className={`${colors[key] ?? colors.unknown} border font-mono text-xs uppercase`}>
      {level ?? "unknown"}
    </Badge>
  );
}
