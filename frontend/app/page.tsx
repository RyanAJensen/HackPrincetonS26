"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const INCIDENT_TYPES = [
  "Mass Casualty / Medical Emergency",
  "Flash Flood with Injuries / Access Limited",
  "Hazmat Exposure / Respiratory Casualties",
  "Severe Storm / Multiple Trauma Casualties",
  "Structure Fire with Victims",
  "Transportation Incident with Injuries",
  "Public Health Emergency",
  "Hazardous Materials Release",
  "Active Threat / Security Incident",
  "Infrastructure Failure",
  "Search and Rescue",
];

const EMPTY_FORM = { incident_type: "", location: "", report: "" };

const DEMO_SCENARIOS = [
  {
    id: "demo-flood",
    label: "Flash Flood with Injuries",
    sub: "Stranded vehicles, injured civilians, delayed EMS access, Washington Road corridor",
    incident_type: "Flash Flood with Injuries / Access Limited",
    location: "Washington Road at Lake Carnegie Bridge, Princeton, NJ",
    report:
      "Heavy rainfall over the past 90 minutes has caused Washington Road to flood at the Lake Carnegie bridge crossing. Water depth is estimated at 18-24 inches and rising rapidly. Four individuals are trapped in two stalled vehicles — one is an elderly female (approx 70s) who is unresponsive; a second occupant has visible head trauma from the collision. Two additional people are ambulatory but stranded on the vehicle roofs. A bystander reports the elderly patient may be in cardiac arrest. Washington Road is the primary EMS corridor to the south side of the jurisdiction — current flooding has made it impassable to standard ambulances. A second water surge is anticipated within 20 minutes as upstream retention basins approach capacity. Penn Medicine Princeton Medical Center has radioed that their trauma bay is nearly full — only 8 beds remain and they have 2 incoming critical patients from an earlier MVA. Capital Health in Trenton has capacity but is 13 miles south.",
  },
  {
    id: "demo-hazmat",
    label: "Hazmat Exposure Event",
    sub: "Respiratory distress risk, decontamination and hospital coordination",
    incident_type: "Hazmat Exposure / Respiratory Casualties",
    location: "Nassau Street Research Facility, Princeton, NJ",
    report:
      "At 2:14 PM, a pressurized cylinder of chlorine gas ruptured in a ground-floor laboratory at a research facility on Nassau Street. Twelve personnel were present in the immediate area. Three occupants have collapsed with severe respiratory distress and are unable to self-evacuate; one is unconscious. Five additional personnel have evacuated but report burning eyes, throat irritation, and difficulty breathing. Four personnel are unaccounted for. The building has not been fully evacuated. Ventilation systems are running, potentially distributing contaminated air to adjacent floors. An estimated 200 additional personnel are in neighboring buildings within the plume zone. Wind is currently 8 mph from the west. No decontamination corridor has been established. Capital Health in Trenton is the only regional facility with full decon capability. Penn Medicine has limited decon capacity and is currently at elevated status from earlier admissions.",
  },
  {
    id: "demo-storm",
    label: "Severe Storm with Multiple Casualties",
    sub: "Structural damage, mixed injury severities, transport route disruption",
    incident_type: "Severe Storm / Multiple Trauma Casualties",
    location: "Princeton Community Center, Witherspoon Street, Princeton, NJ",
    report:
      "A fast-moving severe thunderstorm cell crossed the area at 4:45 PM with sustained winds of 62 mph. A partial roof collapse occurred at the Princeton Community Center on Witherspoon Street — approximately 40 people were inside. Confirmed injuries: 2 patients with crush injuries (one with suspected spinal trauma), 3 with lacerations requiring suturing, 2 with suspected fractures, 1 in respiratory distress from dust inhalation. Approximately 12 additional individuals have minor injuries. A large tree has fallen across Witherspoon Street — the primary EMS route to Penn Medicine Princeton Medical Center is blocked. Penn Medicine is reporting critical capacity: only 4 trauma beds available and their ED is on diversion advisory. The alternate route via Route 1 to Capital Health adds 18 minutes. Robert Wood Johnson in New Brunswick has 11 beds at elevated status. Power is out across 6 blocks. A second storm cell arrives in 22 minutes.",
  },
];

type Step = "home" | "form" | "loading";

export default function LandingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("home");
  const [form, setForm] = useState(EMPTY_FORM);
  const [selectedDemoId, setSelectedDemoId] = useState("");
  const [error, setError] = useState("");
  const [loadingMsg, setLoadingMsg] = useState("");

  const openIncidentDashboard = async (incidentId: string) => {
    setStep("loading");
    setLoadingMsg("Opening live incident dashboard…");
    router.push(`/incidents/${incidentId}`);
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
      await openIncidentDashboard(incident.id);
    } catch (err) {
      setError(String(err));
      setStep("form");
    }
  };

  const handleDemo = (scenarioId: string) => {
    const scenario = DEMO_SCENARIOS.find((item) => item.id === scenarioId);
    if (!scenario) {
      setError("Demo scenario not found.");
      return;
    }
    setError("");
    setSelectedDemoId(scenario.id);
    setForm({
      incident_type: scenario.incident_type,
      location: scenario.location,
      report: scenario.report,
    });
    setStep("form");
  };

  const selectedDemo = DEMO_SCENARIOS.find((item) => item.id === selectedDemoId) ?? null;

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
            Live dashboard first, agent results stream in as they complete
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
            onClick={() => {
              setStep("home");
              setError("");
              setSelectedDemoId("");
              setForm(EMPTY_FORM);
            }}
            className="text-muted-foreground hover:text-foreground text-xs transition-colors"
          >
            ← Back
          </button>
          <span className="text-primary text-sm font-bold tracking-widest">UNILERT</span>
        </header>

        <main className="flex-1 flex items-start justify-center px-6 py-12">
          <div className="w-full max-w-xl space-y-6">
            <div>
              <h1 className="text-xl font-semibold text-foreground mb-1">Report a Medical Emergency</h1>
              <p className="text-sm text-muted-foreground">
                Describe patients, access, and hazards. Unilert generates triage priorities, transport routing, and EMS coordination outputs.
              </p>
            </div>

            {selectedDemo && (
              <div className="rounded border border-primary/30 bg-primary/8 px-4 py-3">
                <p className="text-[10px] uppercase tracking-[0.2em] text-primary font-semibold mb-1">
                  Demo Template Loaded
                </p>
                <p className="text-sm text-foreground font-medium">{selectedDemo.label}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Scenario details are prefilled below. Adjust anything you want before submitting the incident.
                </p>
              </div>
            )}

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
                  What&apos;s Happening
                </label>
                <textarea
                  value={form.report}
                  onChange={(e) => setForm({ ...form, report: e.target.value })}
                  required
                  rows={4}
                  placeholder="Who is injured, how many, severity if known, EMS access, receiving hospital needs…"
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
                {selectedDemo ? "Submit Prefilled Demo Incident →" : "Generate Medical Response IAP →"}
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
                className="w-full flex items-start gap-4 p-4 rounded border border-border bg-card hover:border-primary/50 hover:bg-primary/5 transition-all text-left disabled:opacity-50"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground">{s.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{s.sub}</p>
                </div>
                <span className="text-xs text-muted-foreground shrink-0 mt-0.5">
                  Use Template →
                </span>
              </button>
            ))}
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>
      </main>

      <footer className="border-t border-border px-6 py-3 text-center">
        <p className="text-[10px] text-muted-foreground">
          Unilert · EMS & hospital coordination decision-support · Human review required · Not for autonomous dispatch
        </p>
      </footer>
    </div>
  );
}
