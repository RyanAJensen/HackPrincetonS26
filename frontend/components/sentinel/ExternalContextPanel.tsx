"use client";
import { Badge } from "@/components/ui/badge";

interface WeatherAlert {
  event: string;
  severity: string;
  headline: string;
}

interface ExternalContext {
  geocoded?: boolean;
  coordinates?: { lat: number; lon: number };
  display_address?: string;
  weather_alerts?: WeatherAlert[];
  alert_count?: number;
  forecast?: {
    temperature_f?: number;
    short_forecast?: string;
    wind_speed?: string;
  } | null;
  weather_risk?: string;
  routing?: {
    duration_min?: number;
    distance_mi?: number;
    steps?: string[];
    origin?: string;
  } | null;
  fema_context?: string[];
  weather_driven_threats?: string[];
  replan_triggers?: string[];
  primary_access_route?: string | null;
  alternate_access_route?: string | null;
  healthcare_risks?: string[];
  hospitals?: { name: string; distance_mi?: number | null; trauma_level?: string | null }[];
}

const alertSeverityColor: Record<string, string> = {
  Extreme:  "bg-red-500/20 text-red-400 border-red-500/40",
  Severe:   "bg-orange-500/20 text-orange-400 border-orange-500/40",
  Moderate: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  Minor:    "bg-blue-500/20 text-blue-400 border-blue-500/40",
  Unknown:  "bg-slate-500/20 text-slate-400 border-slate-500/40",
};

const weatherRiskColor: Record<string, string> = {
  high:     "text-red-400",
  moderate: "text-yellow-400",
  none:     "text-green-400",
};

function Row({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="flex gap-2 text-[11px]">
      <span className="text-muted-foreground/60 shrink-0 w-20">{label}</span>
      <span className={accent ?? "text-foreground/80"}>{value}</span>
    </div>
  );
}

export function ExternalContextPanel({ ctx }: { ctx: ExternalContext }) {
  const hasAlerts = (ctx.alert_count ?? 0) > 0;
  const hasRoute = !!ctx.routing;
  const hasGeo = ctx.geocoded && ctx.display_address;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-semibold">
        Live Data Sources
      </p>

      {/* Weather alerts — most prominent */}
      {hasAlerts && ctx.weather_alerts && (
        <div className="rounded border border-orange-500/30 bg-orange-500/8 p-2.5 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold text-orange-400 uppercase tracking-widest">NWS</span>
            <Badge className="bg-orange-500/20 text-orange-400 border-orange-500/30 text-[10px]">
              {ctx.alert_count} Active Alert{(ctx.alert_count ?? 0) > 1 ? "s" : ""}
            </Badge>
          </div>
          {ctx.weather_alerts.map((a, i) => (
            <div key={i} className={`rounded border px-2 py-1.5 text-[10px] ${alertSeverityColor[a.severity] ?? alertSeverityColor.Unknown}`}>
              <span className="font-semibold">{a.event}</span>
              {a.headline && <p className="mt-0.5 opacity-80 line-clamp-2">{a.headline}</p>}
            </div>
          ))}
        </div>
      )}

      {/* No alerts — green status */}
      {!hasAlerts && (
        <div className="rounded border border-border bg-card/30 p-2.5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">NWS</span>
            <span className="text-[10px] text-green-400">No active alerts</span>
          </div>
          {ctx.forecast && (
            <p className="text-[10px] text-muted-foreground mt-1">
              {ctx.forecast.temperature_f != null ? `${ctx.forecast.temperature_f}°F · ` : ""}
              {ctx.forecast.short_forecast}
              {ctx.forecast.wind_speed ? ` · ${ctx.forecast.wind_speed}` : ""}
            </p>
          )}
        </div>
      )}

      {/* Conditions row when alerts present */}
      {hasAlerts && ctx.forecast && (
        <div className="rounded border border-border bg-card/30 p-2 text-[10px] text-muted-foreground">
          Conditions: {ctx.forecast.temperature_f != null ? `${ctx.forecast.temperature_f}°F · ` : ""}
          {ctx.forecast.short_forecast}
          {ctx.forecast.wind_speed ? ` · ${ctx.forecast.wind_speed}` : ""}
        </div>
      )}

      {/* ArcGIS routing */}
      <div className="rounded border border-border bg-card/30 p-2.5 space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">ArcGIS</span>
          {hasRoute
            ? <span className="text-[10px] text-cyan-400">Route computed</span>
            : <span className="text-[10px] text-muted-foreground/50">No API key</span>
          }
        </div>
        {hasGeo && (
          <Row label="Location" value={ctx.display_address!} />
        )}
        {hasRoute && ctx.routing && (
          <>
            <Row label="From" value={ctx.routing.origin ?? "Regional EOC"} />
            <Row
              label="Route"
              value={`${ctx.routing.duration_min} min · ${ctx.routing.distance_mi} mi`}
              accent="text-cyan-400"
            />
            {ctx.primary_access_route && (
              <Row label="Access" value={ctx.primary_access_route} />
            )}
            {ctx.alternate_access_route && (
              <Row label="Alternate" value={ctx.alternate_access_route} accent="text-yellow-400" />
            )}
          </>
        )}
        {!hasRoute && ctx.coordinates && (
          <Row
            label="Coords"
            value={`${ctx.coordinates.lat.toFixed(4)}, ${ctx.coordinates.lon.toFixed(4)}`}
          />
        )}
      </div>

      {/* FEMA context */}
      {ctx.fema_context && ctx.fema_context.length > 0 && (
        <div className="rounded border border-border bg-card/30 p-2.5 space-y-1">
          <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">OpenFEMA</span>
          {ctx.fema_context.map((note, i) => (
            <p key={i} className="text-[10px] text-muted-foreground">{note}</p>
          ))}
        </div>
      )}

      {/* Weather-driven threats injected into plan */}
      {ctx.weather_driven_threats && ctx.weather_driven_threats.length > 0 && (
        <div className="rounded border border-red-500/20 bg-red-500/5 p-2.5 space-y-1">
          <span className="text-[10px] font-bold text-red-400 uppercase tracking-widest">Weather Threats Added to Plan</span>
          {ctx.weather_driven_threats.map((t, i) => (
            <p key={i} className="text-[10px] text-red-300/80">{t}</p>
          ))}
        </div>
      )}

      {/* Replan triggers */}
      {ctx.replan_triggers && ctx.replan_triggers.length > 0 && (
        <div className="rounded border border-yellow-500/20 bg-yellow-500/5 p-2.5 space-y-1">
          <span className="text-[10px] font-bold text-yellow-400 uppercase tracking-widest">Replan Triggers</span>
          {ctx.replan_triggers.slice(0, 3).map((t, i) => (
            <p key={i} className="text-[10px] text-yellow-300/80">▲ {t}</p>
          ))}
        </div>
      )}
    </div>
  );
}
