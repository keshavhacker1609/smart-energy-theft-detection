import { addMinutes } from "date-fns";
import { parseTs } from "./format";
import type { ForecastResult, GridMode, Hour } from "./types";
import { toCsv } from "./utils";

/** Hours in the dashboard window: the first `window_hours` rows from the earliest timestamp. */
export function windowHours(result: ForecastResult): Hour[] {
  return result.hours.slice(0, result.summary.window_hours);
}

export interface ModeSegment {
  mode: GridMode;
  start: Date;
  end: Date;
}

/** Contiguous runs of the same mode, widened by half an hour each side to cover the hour cell. */
export function modeSegments(hours: Hour[]): ModeSegment[] {
  const segments: ModeSegment[] = [];
  for (const hour of hours) {
    const at = parseTs(hour.timestamp);
    const last = segments.at(-1);
    if (last && last.mode === hour.mode && at.getTime() - last.end.getTime() <= 60 * 60 * 1000 * 1.5) {
      last.end = addMinutes(at, 30);
    } else {
      segments.push({ mode: hour.mode, start: addMinutes(at, -30), end: addMinutes(at, 30) });
    }
  }
  return segments;
}

export function hoursToCsv(hours: Hour[]): string {
  return toCsv(
    hours.map((h) => ({
      timestamp: h.timestamp.replace("T", " "),
      ambient_temp_c: h.ambient_temp_c,
      humidity_pct: h.humidity_pct,
      solar_irradiance_wm2: h.solar_irradiance_wm2,
      predicted_kw: Number(h.predicted_kw.toFixed(3)),
      actual_kw: h.actual_kw,
      mode: h.mode,
      critical_overload: h.overload,
      battery_soc_pct: Number(h.soc_pct.toFixed(2)),
      battery_discharge_kw: Number(h.battery_discharge_kw.toFixed(3)),
      grid_kw: Number(h.grid_kw.toFixed(3)),
      battery_reserve_low: h.reserve_low,
      imputed_columns: h.imputed.join(" "),
      reasons: h.reasons.join("; "),
    })),
  );
}
