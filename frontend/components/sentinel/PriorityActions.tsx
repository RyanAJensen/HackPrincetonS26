"use client";
import type { ActionItem, PlanDiff } from "@/lib/api";

interface Props {
  actions: ActionItem[];
  diff: PlanDiff | null;
}

function isNew(item: ActionItem, diff: PlanDiff | null) {
  return diff?.added_actions.some((a) => a.description === item.description) ?? false;
}

export function PriorityActions({ actions, diff }: Props) {
  const top = actions.slice(0, 5);

  return (
    <div className="space-y-2">
      {top.map((action, i) => {
        const added = isNew(action, diff);
        return (
          <div
            key={action.id}
            className={`grid grid-cols-[2rem,minmax(0,1fr)] gap-3 rounded-2xl border px-3 py-3 transition-colors md:grid-cols-[2rem,minmax(0,1fr),auto,auto] md:items-center ${
              added
                ? "border-green-500/30 bg-green-500/8"
                : i === 0
                ? "border-primary/30 bg-primary/8"
                : "border-border/80 bg-card/55"
            }`}
          >
            <span
              className={`flex h-8 w-8 items-center justify-center rounded-xl text-[11px] font-bold ${
                i === 0
                  ? "bg-primary/18 text-primary"
                  : "bg-secondary/80 text-muted-foreground"
              }`}
            >
              {i + 1}
            </span>

            <div className="min-w-0">
              <p className={`text-sm leading-snug ${i === 0 ? "font-semibold text-foreground" : "text-foreground/88"}`}>
                {action.description}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-2 text-[10px] text-muted-foreground md:hidden">
                {action.assigned_to && (
                  <span className="rounded-full border border-border/80 px-2 py-0.5 text-foreground/72">
                    {action.assigned_to}
                  </span>
                )}
                {action.timeframe && <span className="text-muted-foreground/70">{action.timeframe}</span>}
              </div>
            </div>

            {action.assigned_to ? (
              <span className="hidden rounded-full border border-border/80 px-2.5 py-1 text-[10px] text-foreground/72 md:inline-flex">
                {action.assigned_to}
              </span>
            ) : (
              <span className="hidden md:block" />
            )}

            <div className="hidden items-center justify-end gap-2 text-[10px] md:flex">
              {action.timeframe && <span className="text-muted-foreground/70">{action.timeframe}</span>}
              {added && (
                <span className="rounded-full border border-green-500/30 bg-green-500/10 px-2 py-0.5 font-semibold text-green-400">
                  NEW
                </span>
              )}
            </div>

            {added && (
              <span className="col-span-full text-[10px] font-semibold text-green-400 md:hidden">NEW</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
