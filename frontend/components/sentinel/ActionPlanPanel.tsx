"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SeverityBadge } from "./SeverityBadge";
import type { PlanVersion, ActionItem, RoleAssignment } from "@/lib/api";

function ActionList({ items, highlight }: { items: ActionItem[]; highlight?: boolean }) {
  if (!items || items.length === 0) return <p className="text-muted-foreground text-xs">None</p>;
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li
          key={item.id}
          className={`flex gap-3 p-2 rounded border text-xs ${
            highlight ? "border-cyan-500/30 bg-cyan-500/5" : "border-border bg-secondary/30"
          }`}
        >
          <span className="text-muted-foreground shrink-0 mt-0.5">→</span>
          <div className="flex-1 min-w-0">
            <p className="text-foreground leading-snug">{item.description}</p>
            <div className="flex gap-3 mt-1 text-[10px] text-muted-foreground">
              {item.assigned_to && <span>👤 {item.assigned_to}</span>}
              {item.timeframe && <span>⏱ {item.timeframe}</span>}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-2">{title}</h3>
      {children}
    </div>
  );
}

interface Props {
  plan: PlanVersion;
  changedSections?: string[];
}

export function ActionPlanPanel({ plan, changedSections }: Props) {
  const isChanged = (section: string) => changedSections?.includes(section);

  return (
    <div className="space-y-4">
      {/* Summary */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm">Incident Summary</CardTitle>
            <SeverityBadge level={plan.assessed_severity} />
            <span className="text-xs text-muted-foreground ml-auto">
              Confidence: {Math.round(plan.confidence_score * 100)}%
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-foreground/90 leading-relaxed">{plan.incident_summary}</p>
        </CardContent>
      </Card>

      {/* Priorities */}
      <Card className={isChanged("operational_priorities") ? "border-cyan-500/40" : ""}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            Operational Priorities
            {isChanged("operational_priorities") && (
              <Badge className="bg-cyan-500/20 text-cyan-400 border-cyan-500/30 text-[10px]">UPDATED</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-1">
            {plan.operational_priorities.map((p: string, i: number) => (
              <li key={i} className="flex gap-2 text-sm">
                <span className="text-primary font-bold shrink-0">{i + 1}.</span>
                <span>{p}</span>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      {/* Immediate Actions */}
      <Card className={isChanged("immediate_actions") ? "border-cyan-500/40" : ""}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            Immediate Actions
            {isChanged("immediate_actions") && (
              <Badge className="bg-cyan-500/20 text-cyan-400 border-cyan-500/30 text-[10px]">UPDATED</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ActionList items={plan.immediate_actions} highlight={isChanged("immediate_actions")} />
        </CardContent>
      </Card>

      {/* Next 30 Min */}
      <Card className={isChanged("short_term_actions") ? "border-cyan-500/40" : ""}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            Next 30 Minutes
            {isChanged("short_term_actions") && (
              <Badge className="bg-cyan-500/20 text-cyan-400 border-cyan-500/30 text-[10px]">UPDATED</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ActionList items={plan.short_term_actions} highlight={isChanged("short_term_actions")} />
        </CardContent>
      </Card>

      {/* Next 2 Hours */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Next 2 Hours</CardTitle>
        </CardHeader>
        <CardContent>
          <ActionList items={plan.ongoing_actions} />
        </CardContent>
      </Card>

      {/* Role Assignments */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Role Assignments</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {plan.role_assignments.map((r, i) => (
            <div key={i} className="p-2 rounded border border-border bg-secondary/30 text-xs">
              <div className="flex gap-2 items-baseline mb-1">
                <span className="font-semibold text-primary">{r.role}</span>
                <span className="text-muted-foreground">→ {r.assigned_to}</span>
              </div>
              <ul className="space-y-0.5 ml-2">
                {r.responsibilities.map((resp, j) => (
                  <li key={j} className="text-muted-foreground">• {resp}</li>
                ))}
              </ul>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Assumptions */}
      {plan.assumptions.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Assumptions / Unknowns</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {plan.assumptions.map((a) => (
              <div key={a.id} className="p-2 rounded border border-yellow-500/20 bg-yellow-500/5 text-xs">
                <p className="text-foreground">{a.description}</p>
                <p className="text-muted-foreground mt-0.5">Impact: {a.impact}</p>
                <p className="text-yellow-400/70 mt-0.5">Confidence: {Math.round(a.confidence * 100)}%</p>
              </div>
            ))}
            {plan.missing_information.map((m, i) => (
              <div key={i} className="p-2 rounded border border-orange-500/20 bg-orange-500/5 text-xs text-orange-300">
                ⚠ {m}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Risk Notes */}
      {plan.risk_notes.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Risk Notes</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {plan.risk_notes.map((n, i) => (
              <p key={i} className="text-xs text-muted-foreground">• {n}</p>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
