"""
Analytics utilities for Modbus energy data stored in InfluxDB.

This module consolidates the standalone CLI logic so it can be reused by
API endpoints and scheduled tasks. All functions return plain Python /
Pandas structures that callers can serialise as needed.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError

# Default connection parameters; can be overridden via env vars
DEFAULT_INFLUX_URL = "http://localhost:8086"
DEFAULT_INFLUX_TOKEN = (
    "PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ=="
)
DEFAULT_INFLUX_ORG = "DATABRIDGE"
DEFAULT_BUCKET = "databridge"
DEFAULT_MEASUREMENT = "energy_measurements"
DEFAULT_FIELD = "active_energy_import"


@dataclass
class EnergyAnalyticsResult:
    """Container for analytics outputs."""

    start: datetime
    end: datetime
    device_filter: Optional[Iterable[str]]
    raw: pd.DataFrame
    hourly: pd.DataFrame
    daily: pd.DataFrame
    daily_summary: pd.DataFrame
    hourly_comparison: pd.DataFrame
    trend: pd.DataFrame
    anomalies: pd.DataFrame
    performance_scores: Dict[str, Dict[str, float]]


class EnergyAnalyticsError(Exception):
    """Wrapper for recoverable analytics errors."""


def _get_client(url: Optional[str] = None, token: Optional[str] = None, org: Optional[str] = None) -> InfluxDBClient:
    return InfluxDBClient(
        url=url or os.getenv("INFLUX_URL", DEFAULT_INFLUX_URL),
        token=token or os.getenv("INFLUX_TOKEN", DEFAULT_INFLUX_TOKEN),
        org=org or os.getenv("INFLUX_ORG", DEFAULT_INFLUX_ORG),
        timeout=60_000,
        retries=2,
    )


def _build_flux_query(
    bucket: str,
    measurement: str,
    field: str,
    start: datetime,
    stop: datetime,
    devices: Optional[Iterable[str]] = None,
) -> str:
    """
    Build a Flux query that uses downsampled data based on time range to optimize performance:
    - Last 5 days: raw data (energy_measurements)
    - Days 5-35: 1-minute downsampled (energy_measurements_1m)
    - Days 35-215: 5-minute downsampled (energy_measurements_5m)
    - Older: 1-hour downsampled (energy_measurements_1h)
    
    This significantly reduces the number of data points processed, especially for longer time ranges.
    """
    now = datetime.now(timezone.utc)
    days_back = (now - start).total_seconds() / 86400
    cutoff_5d = now - timedelta(days=5)
    cutoff_35d = now - timedelta(days=35)
    cutoff_215d = now - timedelta(days=215)
    
    # Build device filter
    device_filter = ""
    if devices:
        device_pred = " or ".join([f'r["device_id"] == "{device}"' for device in devices])
        device_filter = f' and ({device_pred})'
    
    # Build union query for all relevant measurements based on time range
    measurement_queries = []
    
    # Raw data for last 5 days (if query includes recent data)
    if stop > cutoff_5d:
        raw_start = max(start, cutoff_5d)
        raw_stop = min(stop, now)
        if raw_start < raw_stop:
            # Aggregate raw data to 1-minute intervals to reduce data points
            measurement_queries.append(f'''
  from(bucket: "{bucket}")
    |> range(start: {raw_start.isoformat()}, stop: {raw_stop.isoformat()})
    |> filter(fn: (r) => r["_measurement"] == "{measurement}" and r["_field"] == "{field}"{device_filter})
    |> aggregateWindow(every: 1m, fn: last, createEmpty: false)
    |> keep(columns: ["_time", "_value", "device_id", "location"])
''')
    
    # 1-minute downsampled for days 5-35 (if query includes this range)
    if start < cutoff_5d:
        meas_1m_start = max(start, cutoff_35d)
        meas_1m_stop = min(stop, cutoff_5d)
        if meas_1m_start < meas_1m_stop:
            measurement_queries.append(f'''
  from(bucket: "{bucket}")
    |> range(start: {meas_1m_start.isoformat()}, stop: {meas_1m_stop.isoformat()})
    |> filter(fn: (r) => r["_measurement"] == "{measurement}_1m" and r["_field"] == "{field}"{device_filter})
    |> keep(columns: ["_time", "_value", "device_id", "location"])
''')
    
    # 5-minute downsampled for days 35-215 (if query includes this range)
    if start < cutoff_35d:
        meas_5m_start = max(start, cutoff_215d)
        meas_5m_stop = min(stop, cutoff_35d)
        if meas_5m_start < meas_5m_stop:
            measurement_queries.append(f'''
  from(bucket: "{bucket}")
    |> range(start: {meas_5m_start.isoformat()}, stop: {meas_5m_stop.isoformat()})
    |> filter(fn: (r) => r["_measurement"] == "{measurement}_5m" and r["_field"] == "{field}"{device_filter})
    |> keep(columns: ["_time", "_value", "device_id", "location"])
''')
    
    # 1-hour downsampled for data older than 215 days (if query includes this range)
    if start < cutoff_215d:
        meas_1h_stop = min(stop, cutoff_215d)
        measurement_queries.append(f'''
  from(bucket: "{bucket}")
    |> range(start: {start.isoformat()}, stop: {meas_1h_stop.isoformat()})
    |> filter(fn: (r) => r["_measurement"] == "{measurement}_1h" and r["_field"] == "{field}"{device_filter})
    |> keep(columns: ["_time", "_value", "device_id", "location"])
''')
    
    if not measurement_queries:
        # Fallback to raw data if no downsampled data matches
        measurement_queries.append(f'''
  from(bucket: "{bucket}")
    |> range(start: {start.isoformat()}, stop: {stop.isoformat()})
    |> filter(fn: (r) => r["_measurement"] == "{measurement}" and r["_field"] == "{field}"{device_filter})
    |> keep(columns: ["_time", "_value", "device_id", "location"])
''')
    
    # Union all measurements - raw data is already aggregated to 1m, downsampled data is already at correct resolution
    # No need for additional aggregation since all sources are now at 1-minute resolution
    flux = f'''
union(tables: [{",".join(measurement_queries)}])
  |> sort(columns: ["_time"])
'''
    return flux


def _fetch_energy_data(client: InfluxDBClient, flux: str) -> pd.DataFrame:
    frames = client.query_api().query_data_frame(flux)

    if isinstance(frames, list):
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
    else:
        df = frames

    if df.empty:
        return df

    expected_cols = {"_time", "_value", "device_id", "location"}
    for col in expected_cols - set(df.columns):
        df[col] = pd.NA

    df = df.rename(columns={"_time": "time", "_value": "value"})
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values(["device_id", "time"]).reset_index(drop=True)
    return df


def _compute_hourly_daily(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = df.copy()
    df["value"] = df["value"].astype(float)
    df["device_id"] = df["device_id"].fillna("unknown")
    df["location"] = df["location"].fillna("unknown")

    df["delta"] = (
        df.groupby("device_id")["value"]
        .diff()
        .mask(lambda s: (s < 0) | (s.isna()))
    )
    df["delta"] = df["delta"].mask(df["delta"] < 0)
    df.set_index("time", inplace=True)

    hourly = (
        df.groupby("device_id")["delta"]
        .resample("1h")
        .sum(min_count=1)
        .rename("kwh")
        .reset_index()
    )

    daily = (
        hourly.assign(date=hourly["time"].dt.date)
        .groupby(["device_id", "date"])["kwh"]
        .sum(min_count=1)
        .reset_index()
    )

    return hourly, daily


def _prepare_daily_summary(daily: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Tuple]]:
    if daily.empty:
        return pd.DataFrame(), {}

    rows: List[Dict[str, object]] = []
    context: Dict[str, Tuple] = {}

    for device, group in daily.groupby("device_id"):
        group = group.sort_values("date")
        latest = group.iloc[-1]
        prev = group.iloc[-2] if len(group) > 1 else None

        latest_total = float(latest["kwh"]) if pd.notna(latest["kwh"]) else math.nan

        if prev is not None and pd.notna(prev["kwh"]):
            prev_total = float(prev["kwh"])
            diff = latest_total - prev_total
            pct = (diff / prev_total * 100) if prev_total != 0 else math.nan
            prev_date = prev["date"]
        else:
            prev_total = math.nan
            diff = math.nan
            pct = math.nan
            prev_date = None

        rows.append(
            {
                "device_id": device,
                "date": latest["date"],
                "kwh": latest_total,
                "previous_day_kwh": prev_total,
                "difference_kwh": diff,
                "pct_change": pct,
            }
        )

        context[device] = (
            latest["date"],
            latest_total,
            prev_date,
            prev_total,
        )

    return pd.DataFrame(rows), context


def _prepare_hourly_comparison(hourly: pd.DataFrame, context: Dict[str, Tuple]) -> pd.DataFrame:
    if hourly.empty or not context:
        return pd.DataFrame()

    rows: List[pd.DataFrame] = []

    for device, (latest_date, _, prev_date, _) in context.items():
        device_hours = hourly[hourly["device_id"] == device].copy()
        device_hours["date"] = device_hours["time"].dt.date
        device_hours["hour"] = device_hours["time"].dt.hour

        current_day = device_hours[device_hours["date"] == latest_date][["hour", "kwh"]]
        current_day = current_day.set_index("hour").reindex(range(24))

        if prev_date:
            prev_day = (
                device_hours[device_hours["date"] == prev_date][["hour", "kwh"]]
                .set_index("hour")
                .reindex(range(24))
            )
            prev_values = prev_day["kwh"].values
        else:
            prev_values = [math.nan] * 24

        combined = pd.DataFrame(
            {
                "device_id": device,
                "hour": range(24),
                "current_kwh": current_day["kwh"].values,
                "previous_kwh": prev_values,
            }
        )
        combined["difference_kwh"] = combined["current_kwh"] - combined["previous_kwh"]
        combined["pct_change"] = combined["difference_kwh"] / combined["previous_kwh"] * 100
        mask = combined["previous_kwh"].isna() | (combined["previous_kwh"] == 0)
        combined.loc[mask, "pct_change"] = math.nan
        rows.append(combined)

    return pd.concat(rows, ignore_index=True)


def _compute_trend_and_anomalies(daily: pd.DataFrame, window: int = 7) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if daily.empty:
        return pd.DataFrame(), pd.DataFrame()

    trend = (
        daily.sort_values(["device_id", "date"])
        .groupby("device_id")
        .tail(window)
        .reset_index(drop=True)
    )

    anomalies: List[pd.DataFrame] = []
    for device, group in daily.groupby("device_id"):
        if len(group) < window:
            continue
        recent = group.sort_values("date").tail(window)
        mean = recent["kwh"].mean()
        std = recent["kwh"].std(ddof=0) or 0
        if std == 0:
            continue
        recent = recent.assign(zscore=(recent["kwh"] - mean) / std)
        flagged = recent[recent["zscore"].abs() >= 2].copy()
        if not flagged.empty:
            if "device_id" not in flagged.columns:
                flagged.insert(0, "device_id", device)
            anomalies.append(flagged)

    anomalies_df = pd.concat(anomalies, ignore_index=True) if anomalies else pd.DataFrame()
    return trend, anomalies_df


def _calculate_performance_scores(
    daily_summary: pd.DataFrame,
    hourly: pd.DataFrame,
    target_kwh: Optional[float] = None,
) -> Dict[str, Dict[str, float]]:
    """
    Compute simplified performance / power-quality scores.

    Scores range 0-100:
      - consumption_efficiency: compares latest kWh to target (if provided) or previous day.
      - power_quality: based on variability of hourly consumption (lower variance => higher score).
    """
    if daily_summary.empty:
        return {}

    scores: Dict[str, Dict[str, float]] = {}

    for row in daily_summary.itertuples(index=False):
        device_id = getattr(row, "device_id")
        latest_kwh = getattr(row, "kwh") or math.nan
        previous_kwh = getattr(row, "previous_day_kwh") if hasattr(row, "previous_day_kwh") else math.nan

        # Consumption score
        if target_kwh:
            # Closer to target => higher score
            diff = abs(latest_kwh - target_kwh)
            consumption_score = max(0.0, 100 - (diff / max(target_kwh, 1)) * 100)
        elif previous_kwh and previous_kwh > 0:
            change_pct = (latest_kwh - previous_kwh) / previous_kwh * 100
            consumption_score = max(0.0, 100 - abs(change_pct))
        else:
            consumption_score = 50.0

        # Power quality proxy: variance of hourly consumption for latest day
        device_hours = hourly[hourly["device_id"] == device_id].copy()
        if device_hours.empty:
            quality_score = 50.0
        else:
            device_hours["date"] = device_hours["time"].dt.date
            latest_date = device_hours["date"].max()
            latest_hours = device_hours[device_hours["date"] == latest_date]["kwh"].dropna()
            if latest_hours.empty:
                quality_score = 50.0
            else:
                variance = latest_hours.var(ddof=0)
                quality_score = max(0.0, 100 - min(variance * 20, 100))  # heuristic

        overall = min(100.0, max(0.0, (consumption_score * 0.6 + quality_score * 0.4)))

        scores[device_id] = {
            "consumption_score": round(consumption_score, 2),
            "power_quality_score": round(quality_score, 2),
            "overall_score": round(overall, 2),
        }

    return scores


def run_energy_analytics(
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    days: int = 8,
    devices: Optional[Iterable[str]] = None,
    bucket: str = DEFAULT_BUCKET,
    measurement: str = DEFAULT_MEASUREMENT,
    field: str = DEFAULT_FIELD,
    target_kwh: Optional[float] = None,
) -> EnergyAnalyticsResult:
    """
    Execute the end-to-end analytics workflow and return structured data.
    """
    end_dt = end or datetime.now(timezone.utc)
    start_dt = start or (end_dt - timedelta(days=max(days, 2)))

    if start_dt >= end_dt:
        raise EnergyAnalyticsError("Start time must be before end time.")

    flux = _build_flux_query(
        bucket=bucket,
        measurement=measurement,
        field=field,
        start=start_dt,
        stop=end_dt,
        devices=list(devices) if devices else None,
    )

    try:
        with _get_client() as client:
            raw_df = _fetch_energy_data(client, flux)
    except InfluxDBError as exc:
        raise EnergyAnalyticsError(str(exc)) from exc

    if raw_df.empty:
        return EnergyAnalyticsResult(
            start=start_dt,
            end=end_dt,
            device_filter=list(devices) if devices else None,
            raw=raw_df,
            hourly=pd.DataFrame(),
            daily=pd.DataFrame(),
            daily_summary=pd.DataFrame(),
            hourly_comparison=pd.DataFrame(),
            trend=pd.DataFrame(),
            anomalies=pd.DataFrame(),
            performance_scores={},
        )

    hourly_df, daily_df = _compute_hourly_daily(raw_df)
    daily_summary_df, context = _prepare_daily_summary(daily_df)
    hourly_comparison_df = _prepare_hourly_comparison(hourly_df, context)
    trend_df, anomalies_df = _compute_trend_and_anomalies(daily_df, window=7)
    scores = _calculate_performance_scores(daily_summary_df, hourly_df, target_kwh=target_kwh)

    return EnergyAnalyticsResult(
        start=start_dt,
        end=end_dt,
        device_filter=list(devices) if devices else None,
        raw=raw_df,
        hourly=hourly_df,
        daily=daily_df,
        daily_summary=daily_summary_df,
        hourly_comparison=hourly_comparison_df,
        trend=trend_df,
        anomalies=anomalies_df,
        performance_scores=scores,
    )


def render_csv(frames: Dict[str, pd.DataFrame]) -> str:
    """
    Render multiple dataframes into a CSV-compatible string.

    Frames will be concatenated with section headers.
    """
    output = StringIO()
    for name, df in frames.items():
        output.write(f"# {name}\n")
        if df.empty:
            output.write("No data\n\n")
        else:
            df.to_csv(output, index=False)
            output.write("\n")
    return output.getvalue()


