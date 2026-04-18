"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { PlanDiff } from "@/lib/api";

export function PlanDiffPanel({ diff }: { diff: PlanDiff }) {
  return (
    <div className="space-y-4">
      <Card className="border-cyan-500/30">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm">Plan Updated</CardTitle>
            <Badge className="bg-cyan-500/20 text-cyan-400 border-cyan-500/30 text-[10px]">
              v{diff.from_version} → v{diff.to_version}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-foreground/90">{diff.summary}</p>
          <div className="flex gap-2 flex-wrap mt-3">
            {diff.changed_sections.map((s) => (
              <Badge key={s} className="bg-secondary text-muted-foreground border text-[10px]">
                {s.replace(/_/g, " ")}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {diff.added_actions.length > 0 && (
        <Card className="border-green-500/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-green-400">+ Actions Added</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {diff.added_actions.map((a) => (
              <div key={a.id} className="p-2 rounded border border-green-500/20 bg-green-500/5 text-xs">
                <p className="text-foreground">{a.description}</p>
                {a.assigned_to && <p className="text-muted-foreground mt-0.5">→ {a.assigned_to}</p>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {diff.removed_actions.length > 0 && (
        <Card className="border-red-500/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-red-400">− Actions Removed</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {diff.removed_actions.map((a) => (
              <div key={a.id} className="p-2 rounded border border-red-500/20 bg-red-500/5 text-xs line-through text-muted-foreground">
                {a.description}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {diff.updated_priorities && (
        <Card className="border-yellow-500/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-yellow-400">↑ Updated Priorities</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-1">
              {diff.updated_priorities.map((p, i) => (
                <li key={i} className="text-xs flex gap-2">
                  <span className="text-primary font-bold">{i + 1}.</span>
                  <span>{p}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
