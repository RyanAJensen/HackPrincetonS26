"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  location: string;
  incidentType: string;
}

export function LocationPanel({ location, incidentType }: Props) {
  const encodedLocation = encodeURIComponent(location);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground uppercase tracking-widest">
          Location
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-start gap-3 mb-3">
          <span className="text-2xl">📍</span>
          <div>
            <p className="text-sm font-semibold text-foreground">{location}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{incidentType}</p>
          </div>
        </div>
        {/* Static OpenStreetMap embed */}
        <div className="rounded overflow-hidden border border-border">
          <iframe
            title="Incident Location"
            width="100%"
            height="200"
            src={`https://www.openstreetmap.org/export/embed.html?bbox=-74.667%2C40.340%2C-74.648%2C40.352&layer=mapnik&marker=40.3461%2C-74.6580`}
            style={{ border: 0, filter: "invert(90%) hue-rotate(180deg)" }}
          />
        </div>
        <p className="text-[10px] text-muted-foreground mt-2 text-center">
          {location}
        </p>
      </CardContent>
    </Card>
  );
}
