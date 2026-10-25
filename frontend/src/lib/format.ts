import { format, parseISO } from "date-fns";
import type { GridMode } from "./types";

// Forecast timestamps are naive local times from the telemetry; parseISO keeps them as-is.
export const parseTs = (iso: string): Date => parseISO(iso);
export const fmtClock = (iso: string): string => format(parseTs(iso), "HH:mm");
export const fmtDayClock = (iso: string): string => format(parseTs(iso), "d MMM HH:mm");
export const fmtDateTime = (iso: string): string => format(parseTs(iso), "yyyy-MM-dd HH:mm");

export const fmtKw = (value: number, digits = 1): string => `${value.toFixed(digits)} kW`;
export const fmtPct = (value: number, digits = 0): string => `${value.toFixed(digits)}%`;

export function fmtSigned(value: number, digits = 1, unit = ""): string {
  const rounded = Number(value.toFixed(digits));
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "±";
  return `${sign}${Math.abs(rounded).toFixed(digits)}${unit}`;
}

export const MODE_LABEL: Record<GridMode, string> = {
  MAIN_GRID: "Main grid",
  RENEWABLE_STORAGE: "Renewable storage",
};
