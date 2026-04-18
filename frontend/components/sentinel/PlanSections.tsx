"use client";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SeverityBadge } from "./SeverityBadge";
import type { PlanVersion, ActionItem, PlanDiff } from "@/lib/api";

// --- helpers ---

function isAdded(item: ActionItem, diff: PlanDiff | null) {
  if (!diff) return false;
  return diff.added_actions.some((a) => a.description === item.description);
}

function isRemoved(item: ActionItem, diff: PlanDiff | null) {
  if (!diff) return false;
  return diff.removed_actions.some((a) => a.description === item.description);
}

// --- Section heading with unit attribution ---

function SectionLabel({
  label,
  unit,
  changed,
  sub,
}: {
  label: string;
  unit?: string;
  changed?: boolean;
  sub?: string;
}) {
  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{label}</h3>
        {unit && (
          <span className="text-[10px] text-muted-foreground/50">— {unit}</span>
        )}
        {changed && (
          <Badge className="bg-yellow-500/20 text-yellow-400 border-yellow-500/30 text-[10px]">Updated</Badge>
        )}
      </div>
      {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

// --- Action row ---

function ActionRow({ item, diff }: { item: ActionItem; diff: PlanDiff | null }) {
  const added = isAdded(item, diff);
  const removed = isRemoved(item, diff);

  return (
    <li
      className={`flex gap-3 p-3 rounded border text-xs transition-colors ${
        added
          ? "border-green-500/40 bg-green-500/8"
          : removed
          ? "border-red-500/30 bg-red-500/5 opacity-60"
          : "border-border bg-card/30"
      }`}
    >
      <span className="shrink-0 mt-0.5 font-bold">
        {added
          ? <span className="text-green-400">+</span>
          : removed
          ? <span className="text-red-400 line-through">−</span>
          : <span className="text-primary">→</span>
        }
      </span>
      <div className="flex-1 min-w-0">
        <p className={`leading-snug ${removed ? "line-through text-muted-foreground" : "text-foreground"}`}>
          {item.description}
        </p>
        <div className="flex flex-wrap gap-3 mt-1.5 text-[10px] text-muted-foreground">
          {item.assigned_to && (
            <span className="flex items-center gap-1">
              <span className="text-muted-foreground/50">Owner:</span> {item.assigned_to}
            </span>
          )}
          {item.timeframe && (
            <span className="flex items-center gap-1">
              <span className="text-muted-foreground/50">By:</span> {item.timeframe}
            </span>
          )}
        </div>
      </div>
      {added && (
        <Badge className="bg-green-500/20 text-green-400 border-green-500/30 text-[10px] shrink-0 self-start">
          NEW
        </Badge>
      )}
    </li>
  );
}

function ActionSection({
  label,
  unit,
  sub,
  items,
  diff,
  changed,
}: {
  label: string;
  unit: string;
  sub: string;
  items: ActionItem[];
  diff: PlanDiff | null;
  changed?: boolean;
}) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <SectionLabel label={label} unit={unit} sub={sub} changed={changed} />
      <ul className="space-y-2">
        {items.map((item) => (
          <ActionRow key={item.id} item={item} diff={diff} />
        ))}
      </ul>
    </div>
  );
}

// --- Main export ---

interface Props {
  plan: PlanVersion;
  diff: PlanDiff | null;
  changedSections?: string[];
}

export function PlanSections({ plan, diff, changedSections }: Props) {
  const changed = (s: string) => changedSections?.includes(s);

  return (
    <div className="space-y-4">
      {/* Diff summary banner */}
      {diff && (
        <div className="p-3 rounded border border-cyan-500/30 bg-cyan-500/8 text-xs space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-cyan-400 font-semibold">Plan Revised</span>
            <Badge className="bg-cyan-500/20 text-cyan-400 border-cyan-500/30 text-[10px]">
              v{diff.from_version} → v{diff.to_version}
            </Badge>
          </div>
          <p className="text-muted-foreground">{diff.summary}</p>
          {diff.changed_sections.length > 0 && (
            <div className="flex gap-1.5 flex-wrap pt-0.5">
              <span className="text-[10px] text-muted-foreground/60">Sections revised:</span>
              {diff.changed_sections.map((s) => (
                <Badge key={s} className="bg-secondary text-muted-foreground border text-[10px]">
                  {s.replace(/_/g, " ")}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Incident Brief — Situation Unit */}
      <Card>
        <CardHeader className="pb-2">
          <SectionLabel
            label="Incident Brief"
            unit="Situation Unit"
            sub="Verified operational picture — shared basis for all response decisions."
          />
          <div className="flex items-center gap-2">
            <SeverityBadge level={plan.assessed_severity} />
            <span className="text-[10px] text-muted-foreground">
              Confidence {Math.round(plan.confidence_score * 100)}%
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-foreground/90 leading-relaxed">{plan.incident_summary}</p>
        </CardContent>
      </Card>

      {/* Top Priorities — Threat Analysis Unit */}
      <Card className={changed("severity") ? "border-yellow-500/40" : ""}>
        <CardHeader className="pb-2">
          <SectionLabel
            label="Priority Threats"
            unit="Threat Analysis Unit"
            sub="Ranked by severity and potential for escalation. Address in order."
            changed={changed("severity")}
          />
        </CardHeader>
        <CardContent>
          {plan.risk_notes.length === 0 ? (
            <p className="text-xs text-muted-foreground">No priority threats listed.</p>
          ) : (
          <ol className="space-y-2">
            {plan.risk_notes.map((p: string, i: number) => (
              <li key={i} className="flex gap-3 text-sm">
                <span
                  className={`shrink-0 font-bold w-5 text-center rounded text-[11px] leading-5 h-5 ${
                    i === 0
                      ? "bg-red-500/20 text-red-400"
                      : i === 1
                      ? "bg-orange-500/20 text-orange-400"
                      : "bg-secondary text-muted-foreground"
                  }`}
                >
                  {i + 1}
                </span>
                <span className="text-foreground/90">{p}</span>
              </li>
            ))}
          </ol>
          )}
        </CardContent>
      </Card>

      {/* Immediate Actions — Operations Planner */}
      <Card className={changed("immediate_actions") ? "border-yellow-500/40" : ""}>
        <CardContent className="pt-4">
          <ActionSection
            label="Immediate Action Plan"
            unit="Operations Planner"
            sub="Actions that must be underway within the first 10 minutes."
            items={plan.immediate_actions}
            diff={diff}
            changed={changed("immediate_actions")}
          />
        </CardContent>
      </Card>

      {/* 30-min plan */}
      <Card className={changed("short_term_actions") ? "border-yellow-500/40" : ""}>
        <CardContent className="pt-4">
          <ActionSection
            label="30-Minute Plan"
            unit="Operations Planner"
            sub="Actions to execute once the immediate response is underway."
            items={plan.short_term_actions}
            diff={diff}
            changed={changed("short_term_actions")}
          />
        </CardContent>
      </Card>

      {/* 2-hour plan */}
      {plan.ongoing_actions.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <ActionSection
              label="2-Hour Plan"
              unit="Operations Planner"
              sub="Sustained response and recovery actions."
              items={plan.ongoing_actions}
              diff={diff}
            />
          </CardContent>
        </Card>
      )}

      {/* Role Assignments */}
      {plan.role_assignments.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <SectionLabel
              label="Role Assignments"
              unit="Operations Planner"
              sub="Each person has one role and clear responsibilities. No overlap."
              changed={changed("role_assignments")}
            />
          </CardHeader>
          <CardContent className="space-y-2">
            {plan.role_assignments.map((r, i) => (
              <div key={i} className="p-3 rounded border border-border bg-card/30 text-xs">
                <div className="flex gap-2 items-baseline mb-2">
                  <span className="font-semibold text-primary">{r.role}</span>
                  <span className="text-muted-foreground">→</span>
                  <span className="text-foreground font-medium">{r.assigned_to}</span>
                </div>
                <ul className="space-y-1 ml-2">
                  {r.responsibilities.map((resp, j) => (
                    <li key={j} className="text-muted-foreground flex gap-1.5">
                      <span className="text-primary/50 shrink-0">·</span>
                      {resp}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Assumptions / Unknowns */}
      {(plan.assumptions.length > 0 || plan.missing_information.length > 0) && (
        <Card>
          <CardHeader className="pb-2">
            <SectionLabel
              label="Critical Unknowns"
              unit="Situation Unit"
              sub="Gaps in the current picture. Each one could change the plan."
            />
          </CardHeader>
          <CardContent className="space-y-2">
            {plan.assumptions.map((a) => (
              <div key={a.id} className="p-2.5 rounded border border-yellow-500/20 bg-yellow-500/5 text-xs">
                <div className="flex items-start gap-2">
                  <span className="text-yellow-400 shrink-0 mt-0.5">⚠</span>
                  <div>
                    <p className="text-foreground font-medium">{a.description}</p>
                    <p className="text-muted-foreground mt-0.5">
                      If wrong: {a.impact}
                    </p>
                  </div>
                  <span className="ml-auto text-[10px] text-yellow-400/60 shrink-0">
                    {Math.round(a.confidence * 100)}% confident
                  </span>
                </div>
              </div>
            ))}
            {plan.missing_information.map((m, i) => (
              <div key={i} className="p-2.5 rounded border border-orange-500/20 bg-orange-500/5 text-xs flex gap-2">
                <span className="text-orange-400 shrink-0">!</span>
                <span className="text-orange-200">Confirm immediately: {m}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Risk Notes */}
      {plan.risk_notes.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <SectionLabel
              label="Escalation Watchlist"
              unit="Threat Analysis Unit"
              sub="Conditions that would require an immediate plan revision."
            />
          </CardHeader>
          <CardContent className="space-y-1.5">
            {plan.risk_notes.map((n, i) => (
              <div key={i} className="flex gap-2 text-xs">
                <span className="text-red-400/60 shrink-0">▲</span>
                <span className="text-muted-foreground">{n}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
