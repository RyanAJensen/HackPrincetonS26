"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { PlanVersion } from "@/lib/api";

interface Props {
  versions: PlanVersion[];
  currentVersion: number;
  onSelect: (version: number) => void;
}

export function PlanVersionHistory({ versions, currentVersion, onSelect }: Props) {
  if (versions.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground uppercase tracking-widest">
          Plan History
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {[...versions].reverse().map((v) => (
          <button
            key={v.version}
            onClick={() => onSelect(v.version)}
            className={`w-full text-left p-2 rounded border text-xs transition-colors ${
              v.version === currentVersion
                ? "border-primary/60 bg-primary/10 text-foreground"
                : "border-border bg-card text-muted-foreground hover:border-border/80 hover:text-foreground"
            }`}
          >
            <div className="flex items-center gap-2">
              <span className="font-semibold">v{v.version}</span>
              {v.version === currentVersion && (
                <Badge className="bg-primary/20 text-primary border-primary/30 text-[10px]">current</Badge>
              )}
              <span className="ml-auto text-[10px] text-muted-foreground">
                {new Date(v.created_at).toLocaleTimeString()}
              </span>
            </div>
            {v.trigger !== "initial" && (
              <p className="text-[10px] text-muted-foreground mt-0.5 truncate">
                Update: {v.trigger}
              </p>
            )}
          </button>
        ))}
      </CardContent>
    </Card>
  );
}
