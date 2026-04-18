"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { CommunicationDraft } from "@/lib/api";

// Map backend audience values to clean operational labels
const AUDIENCE_CONFIG: Record<string, {
  tab: string;
  label: string;
  sublabel: string;
  urgencyColor: string;
  icon: string;
}> = {
  "ems responders": {
    tab: "EMS",
    label: "EMS Responder Brief",
    sublabel: "Triage, transport, and receiving-facility coordination",
    urgencyColor: "bg-red-500/20 text-red-400 border-red-500/30",
    icon: "🚨",
  },
  ems: {
    tab: "EMS",
    label: "EMS Responder Brief",
    sublabel: "Triage, transport, and receiving-facility coordination",
    urgencyColor: "bg-red-500/20 text-red-400 border-red-500/30",
    icon: "🚨",
  },
  responders: {
    tab: "EMS",
    label: "EMS / Responder Brief",
    sublabel: "Field EMS and first responders",
    urgencyColor: "bg-red-500/20 text-red-400 border-red-500/30",
    icon: "🚨",
  },
  "receiving hospitals": {
    tab: "Hospitals",
    label: "Hospital Notification",
    sublabel: "Receiving facilities — incoming patients and ETA",
    urgencyColor: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    icon: "🏥",
  },
  hospital: {
    tab: "Hospitals",
    label: "Hospital Notification",
    sublabel: "Receiving facilities — incoming patients and ETA",
    urgencyColor: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    icon: "🏥",
  },
  "campus community": {
    tab: "Public",
    label: "Public Advisory",
    sublabel: "Public emergency alert system",
    urgencyColor: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    icon: "📢",
  },
  public: {
    tab: "Public",
    label: "Public Advisory",
    sublabel: "Public emergency alert system",
    urgencyColor: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    icon: "📢",
  },
  administration: {
    tab: "Leadership",
    label: "Leadership Update",
    sublabel: "Agency leadership and senior staff",
    urgencyColor: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    icon: "📋",
  },
};

function getConfig(draft: CommunicationDraft) {
  const keys = Object.keys(AUDIENCE_CONFIG).sort((a, b) => b.length - a.length);
  const key = keys.find((k) => draft.audience.toLowerCase().includes(k.toLowerCase()));
  return key ? AUDIENCE_CONFIG[key] : {
    tab: draft.audience,
    label: draft.audience,
    sublabel: `via ${draft.channel}`,
    urgencyColor: "bg-slate-500/20 text-slate-400 border-slate-500/30",
    icon: "📄",
  };
}

function CommCard({ draft }: { draft: CommunicationDraft }) {
  const cfg = getConfig(draft);

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-start gap-3">
          <span className="text-xl mt-0.5">{cfg.icon}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-foreground">{cfg.label}</span>
              <Badge className={`${cfg.urgencyColor} border text-[10px] uppercase`}>
                {draft.urgency}
              </Badge>
            </div>
            <p className="text-[10px] text-muted-foreground mt-0.5">{cfg.sublabel}</p>
            {draft.subject && (
              <p className="text-xs font-medium text-foreground/80 mt-2 border-l-2 border-primary/40 pl-2">
                {draft.subject}
              </p>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="p-3 rounded bg-secondary/40 border border-border">
          <p className="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap font-mono">
            {draft.body}
          </p>
        </div>
        <p className="text-[10px] text-muted-foreground mt-2">
          Ready to send · {draft.channel.replace(/_/g, " ")}
        </p>
      </CardContent>
    </Card>
  );
}

// Preferred display order: EMS → hospitals → public → leadership
const PRIORITY_ORDER = ["ems responders", "ems", "responders", "receiving hospitals", "hospital", "public", "campus community", "administration"];

function sortDrafts(drafts: CommunicationDraft[]): CommunicationDraft[] {
  return [...drafts].sort((a, b) => {
    const ai = PRIORITY_ORDER.findIndex((k) => a.audience.toLowerCase().includes(k));
    const bi = PRIORITY_ORDER.findIndex((k) => b.audience.toLowerCase().includes(k));
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
}

export function CommunicationsPanel({ communications }: { communications: CommunicationDraft[] }) {
  const sorted = sortDrafts(communications ?? []);
  const [active, setActive] = useState(0);

  if (sorted.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground text-sm">
          No communications drafted yet.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Officer header */}
      <div className="p-3 rounded border border-border bg-card/50">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Communications Officer</span>
          <span className="text-[10px] text-green-400">● Alerts drafted</span>
        </div>
        <p className="text-xs text-muted-foreground">
          {sorted.length} message{sorted.length !== 1 ? "s" : ""} drafted — each targeted to its audience and ready to send.
        </p>
      </div>

      {/* Audience tab switcher */}
      {sorted.length > 1 && (
        <div className="flex gap-1 border-b border-border">
          {sorted.map((d, i) => {
            const cfg = getConfig(d);
            return (
              <button
                key={d.id}
                onClick={() => setActive(i)}
                className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                  active === i
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {cfg.tab}
              </button>
            );
          })}
        </div>
      )}

      {/* Active draft */}
      <CommCard draft={sorted[active]} />
    </div>
  );
}
