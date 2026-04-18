"""
NWS (National Weather Service) service — active alerts and forecast.

Uses the free NWS API (no key required). Fetches alerts and forecast for the
incident's coordinates. Alert data feeds directly into the Threat Analysis Unit
to generate weather-driven escalation triggers.
"""
from __future__ import annotations
import httpx
from typing import Optional

NWS_BASE = "https://api.weather.gov"
# Princeton, NJ default coordinates — used when geocoding is unavailable
PRINCETON_LAT = 40.3573
PRINCETON_LON = -74.6672


async def _get_forecast_office(lat: float, lon: float) -> Optional[dict]:
    """Resolve grid coordinates from lat/lon."""
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "Unilert/1.0 (campus-response)"}) as client:
            r = await client.get(f"{NWS_BASE}/points/{lat:.4f},{lon:.4f}")
            if r.status_code != 200:
                return None
            return r.json().get("properties", {})
    except Exception:
        return None


async def get_active_alerts(lat: float, lon: float) -> list[dict]:
    """
    Return active NWS alerts affecting the area.
    Each alert: {event, severity, headline, description, urgency, effective, expires}.
    """
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "Unilert/1.0 (campus-response)"}) as client:
            r = await client.get(
                f"{NWS_BASE}/alerts/active",
                params={"point": f"{lat:.4f},{lon:.4f}", "status": "actual"},
            )
            if r.status_code != 200:
                return []
        features = r.json().get("features", [])
        alerts = []
        for f in features[:5]:
            props = f.get("properties", {})
            alerts.append({
                "event": props.get("event", "Unknown Alert"),
                "severity": props.get("severity", "Unknown"),
                "urgency": props.get("urgency", "Unknown"),
                "headline": props.get("headline", ""),
                "description": (props.get("description") or "")[:300],
                "effective": props.get("effective", ""),
                "expires": props.get("expires", ""),
                "areas": props.get("areaDesc", ""),
            })
        return alerts
    except Exception:
        return []


async def get_forecast_summary(lat: float, lon: float) -> Optional[dict]:
    """
    Return current conditions from NWS hourly forecast.
    {temperature_f, wind_speed, wind_direction, short_forecast, detailed_forecast}
    """
    try:
        office = await _get_forecast_office(lat, lon)
        if not office:
            return None
        forecast_url = office.get("forecastHourly")
        if not forecast_url:
            return None
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "Unilert/1.0 (campus-response)"}) as client:
            r = await client.get(forecast_url)
            if r.status_code != 200:
                return None
        periods = r.json().get("properties", {}).get("periods", [])
        if not periods:
            return None
        now = periods[0]
        return {
            "temperature_f": now.get("temperature"),
            "wind_speed": now.get("windSpeed", ""),
            "wind_direction": now.get("windDirection", ""),
            "short_forecast": now.get("shortForecast", ""),
            "detailed_forecast": now.get("detailedForecast", "")[:200],
            "is_daytime": now.get("isDaytime", True),
        }
    except Exception:
        return None


def _classify_weather_risk(alerts: list[dict], forecast: Optional[dict]) -> dict:
    """
    Derive structured risk signals from weather data for the Threat Analysis Unit.
    """
    high_risk_events = {
        "Flash Flood Warning", "Tornado Warning", "Severe Thunderstorm Warning",
        "Winter Storm Warning", "Ice Storm Warning", "Blizzard Warning",
        "Extreme Cold Warning", "Excessive Heat Warning",
    }
    moderate_risk_events = {
        "Flash Flood Watch", "Tornado Watch", "Severe Thunderstorm Watch",
        "Winter Storm Watch", "Flood Advisory", "Wind Advisory",
        "Dense Fog Advisory", "Special Weather Statement",
    }

    escalation_triggers = []
    threats = []
    severity = "none"

    for alert in alerts:
        event = alert["event"]
        if any(e in event for e in high_risk_events):
            severity = "high"
            threats.append(f"ACTIVE {event}: {alert['headline'][:120]}")
            escalation_triggers.append(f"{event} in effect — reassess outdoor operations immediately")
        elif any(e in event for e in moderate_risk_events):
            if severity != "high":
                severity = "moderate"
            threats.append(f"{event}: {alert['headline'][:100]}")
            escalation_triggers.append(f"{event} — monitor conditions for rapid deterioration")

    if forecast:
        temp = forecast.get("temperature_f")
        wind = forecast.get("wind_speed", "")
        conditions = forecast.get("short_forecast", "").lower()
        if temp and temp >= 95:
            threats.append(f"Extreme heat: {temp}°F — heat casualty risk elevated for outdoor response")
            escalation_triggers.append("Temperature exceeds 95°F — rotate responders, deploy cooling stations")
        if temp and temp <= 20:
            threats.append(f"Extreme cold: {temp}°F — hypothermia risk for prolonged outdoor exposure")
        if "flood" in conditions:
            escalation_triggers.append("Active flooding reported — verify all access routes before dispatch")
        if "thunder" in conditions:
            escalation_triggers.append("Lightning risk — suspend outdoor operations if strike within 5 miles")

    return {
        "severity": severity,
        "weather_threats": threats,
        "escalation_triggers": escalation_triggers,
        "has_active_alerts": len(alerts) > 0,
        "alert_count": len(alerts),
    }


async def get_weather_context(lat: float, lon: float) -> dict:
    """Full weather enrichment for agent pipeline."""
    import asyncio
    alerts, forecast = await asyncio.gather(
        get_active_alerts(lat, lon),
        get_forecast_summary(lat, lon),
    )
    risk = _classify_weather_risk(alerts, forecast)
    return {
        "alerts": alerts,
        "forecast": forecast,
        "risk": risk,
        "available": True,
    }
