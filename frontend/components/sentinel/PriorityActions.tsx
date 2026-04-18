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
            className={`flex gap-4 items-start p-4 rounded-lg border transition-colors ${
              added
                ? "border-green-500/30 bg-green-500/6"
                : i === 0
                ? "border-primary/25 bg-primary/5"
                : "border-border bg-card/40"
            }`}
          >
            {/* Number */}
            <span
              className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold mt-0.5 ${
                i === 0
                  ? "bg-primary/20 text-primary"
                  : "bg-secondary text-muted-foreground"
              }`}
            >
              {i + 1}
            </span>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <p className={`text-sm leading-snug ${i === 0 ? "font-semibold text-foreground" : "text-foreground/90"}`}>
                {action.description}
              </p>
              <div className="flex gap-3 mt-1.5 text-[10px] text-muted-foreground">
                {action.assigned_to && <span>{action.assigned_to}</span>}
                {action.timeframe && <span className="text-muted-foreground/60">· {action.timeframe}</span>}
              </div>
            </div>

            {added && (
              <span className="shrink-0 text-[10px] text-green-400 font-semibold mt-1">NEW</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
