"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const INCIDENT_TYPES = [
  "Structure Fire",
  "Mass Casualty / Medical Emergency",
  "Hazardous Materials Release",
  "Active Threat / Security Incident",
  "Severe Weather / Natural Disaster",
  "Infrastructure Failure",
  "Flash Flood / Access Disruption",
  "Public Health Emergency",
  "Search and Rescue",
  "Transportation Incident",
];

const DEMO_SCENARIOS = [
  {
    id: "demo-flood",
    label: "Flash Flood — Trapped Patients, EMS Access Blocked",
    sub: "4 patients trapped, critical transport window closing, delayed EMS access",
  },
  {
    id: "demo-hazmat",
    label: "Hazmat Exposure — Respiratory Casualties",
    sub: "Chlorine gas release, 8 patients with respiratory distress, decon triage required",
  },
  {
    id: "demo-storm",
    label: "Severe Storm — Multi-Trauma Mass Casualty",
    sub: "Building collapse, 8+ injuries, critical patients, blocked transport routes",
  },
];

type Step = "home" | "form" | "loading";

export default function LandingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("home");
  const [form, setForm] = useState({ incident_type: "", location: "", report: "" });
  const [loadingDemo, setLoadingDemo] = useState("");
  const [error, setError] = useState("");
  const [loadingMsg, setLoadingMsg] = useState("");

  const startAnalysis = async (incidentId: string) => {
    setStep("loading");
    setLoadingMsg("Analyzing incident and generating response plan…");
    try {
      await api.incidents.analyze(incidentId);
      router.push(`/incidents/${incidentId}`);
    } catch {
      // Still navigate — incident page will handle the error state
      router.push(`/incidents/${incidentId}`);
    }
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setStep("loading");
    setLoadingMsg("Creating incident…");
    try {
      const incident = await api.incidents.create({
        incident_type: form.incident_type,
        location: form.location,
        report: form.report,
      });
      setLoadingMsg("Analyzing incident and generating response plan…");
      await startAnalysis(incident.id);
    } catch (err) {
      setError(String(err));
      setStep("form");
    }
  };

  const handleDemo = async (scenarioId: string) => {
    setLoadingDemo(scenarioId);
    setError("");
    try {
      const incident = await api.demo.load(scenarioId);
      setStep("loading");
      setLoadingMsg("Analyzing incident and generating response plan…");
      await startAnalysis(incident.id);
    } catch (err) {
      setError(String(err));
      setLoadingDemo("");
    }
  };

  // --- Loading screen ---
  if (step === "loading") {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-6">
        <div className="text-center space-y-4">
          <div className="flex items-center justify-center gap-2">
            <span className="text-primary text-sm font-bold tracking-widest">UNILERT</span>
          </div>
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-foreground font-medium">{loadingMsg}</p>
          <p className="text-xs text-muted-foreground">
            Situation → Medical Impact → Triage → Patient Transport → Communications
          </p>
        </div>
      </div>
    );
  }

  // --- Incident form ---
  if (step === "form") {
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <header className="border-b border-border px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => { setStep("home"); setError(""); setForm({ incident_type: "", location: "", report: "" }); }}
            className="text-muted-foreground hover:text-foreground text-xs transition-colors"
          >
            ← Back
          </button>
          <span className="text-primary text-sm font-bold tracking-widest">UNILERT</span>
        </header>

        <main className="flex-1 flex items-start justify-center px-6 py-12">
          <div className="w-full max-w-xl space-y-6">
            <div>
              <h1 className="text-xl font-semibold text-foreground mb-1">Report an Incident</h1>
              <p className="text-sm text-muted-foreground">
                Describe what's happening. We'll generate a structured response plan.
              </p>
            </div>

            <form onSubmit={handleFormSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <label className="text-[10px] text-muted-foreground uppercase tracking-widest font-semibold">
                  Incident Type
                </label>
                <select
                  value={form.incident_type}
                  onChange={(e) => setForm({ ...form, incident_type: e.target.value })}
                  required
                  className="w-full px-3 py-2.5 rounded border border-border bg-input text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">Select type…</option>
                  {INCIDENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] text-muted-foreground uppercase tracking-widest font-semibold">
                  Location
                </label>
                <input
                  value={form.location}
                  onChange={(e) => setForm({ ...form, location: e.target.value })}
                  required
                  placeholder="e.g. Main St & Oak Ave, Springfield"
                  className="w-full px-3 py-2.5 rounded border border-border bg-input text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] text-muted-foreground uppercase tracking-widest font-semibold">
                  What's Happening
                </label>
                <textarea
                  value={form.report}
                  onChange={(e) => setForm({ ...form, report: e.target.value })}
                  required
                  rows={4}
                  placeholder="Describe the situation — what happened, who is affected, immediate hazards…"
                  className="w-full px-3 py-2.5 rounded border border-border bg-input text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              {error && (
                <p className="text-sm text-red-400 p-3 rounded border border-red-500/30 bg-red-500/10">{error}</p>
              )}

              <Button
                type="submit"
                className="w-full h-11 bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-semibold"
              >
                Generate Response Plan →
              </Button>
            </form>
          </div>
        </main>
      </div>
    );
  }

  // --- Home screen ---
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center">
        <span className="text-primary text-sm font-bold tracking-widest">UNILERT</span>
        <span className="ml-3 text-[10px] text-muted-foreground border border-border rounded px-1.5 py-0.5">ALPHA</span>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center px-6 py-16 text-center">
        <div className="max-w-lg space-y-8">
          {/* Hero */}
          <div className="space-y-3">
            <h1 className="text-2xl font-semibold text-foreground leading-tight">
              Medical triage and emergency<br />response coordination
            </h1>
            <p className="text-sm text-muted-foreground">
              AI agents analyze incidents to produce triage priorities, patient transport plans,
              and hospital coordination — updated in real time as conditions change.
            </p>
          </div>

          {/* Primary CTA */}
          <div className="flex flex-col gap-3">
            <Button
              onClick={() => setStep("form")}
              className="h-12 text-sm font-semibold bg-primary text-primary-foreground hover:bg-primary/90"
            >
              Start New Incident →
            </Button>
          </div>

          {/* Divider */}
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground uppercase tracking-widest">
            <div className="flex-1 h-px bg-border" />
            or try a demo scenario
            <div className="flex-1 h-px bg-border" />
          </div>

          {/* Demo scenarios */}
          <div className="space-y-2 text-left">
            {DEMO_SCENARIOS.map((s) => (
              <button
                key={s.id}
                onClick={() => handleDemo(s.id)}
                disabled={!!loadingDemo}
                className="w-full flex items-start gap-4 p-4 rounded border border-border bg-card hover:border-primary/50 hover:bg-primary/5 transition-all text-left disabled:opacity-50"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground">{s.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{s.sub}</p>
                </div>
                <span className="text-xs text-muted-foreground shrink-0 mt-0.5">
                  {loadingDemo === s.id ? "Loading…" : "Run →"}
                </span>
              </button>
            ))}
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>
      </main>

      <footer className="border-t border-border px-6 py-3 text-center">
        <p className="text-[10px] text-muted-foreground">
          Decision-support tool · All outputs require human review before action · Not for autonomous emergency control
        </p>
      </footer>
    </div>
  );
}
