"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface Props {
  onReplan: (updateText: string) => void;
  isLoading: boolean;
}

const QUICK_UPDATES = [
  "Primary access road is blocked — reroute all vehicles via Service Drive",
  "Building occupancy is higher than expected — approximately 40% more people on site",
  "Chemical exposure confirmed — three individuals require immediate decontamination",
  "Mutual aid has arrived — two additional fire units and one hazmat team on scene",
  "Victim count has increased — additional injuries reported",
];

export function ReplanForm({ onReplan, isLoading }: Props) {
  const [text, setText] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (text.trim()) onReplan(text.trim());
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground uppercase tracking-widest">
          Submit Field Update
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground mb-3">
          New information from the field will trigger replanning. The system will show a diff of what changed.
        </p>
        <form onSubmit={handleSubmit} className="space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Road is blocked, reroute via Service Drive…"
            className="w-full h-24 px-3 py-2 rounded border border-border bg-input text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-1 focus:ring-ring"
            disabled={isLoading}
          />
          <div className="flex gap-2 flex-wrap">
            {QUICK_UPDATES.map((u, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setText(u)}
                className="text-[10px] px-2 py-1 rounded border border-border bg-secondary text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors"
              >
                {u.slice(0, 40)}…
              </button>
            ))}
          </div>
          <Button
            type="submit"
            disabled={isLoading || !text.trim()}
            className="w-full bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {isLoading ? "Replanning…" : "Submit Update & Replan"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
