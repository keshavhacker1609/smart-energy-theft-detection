import { createContext, useContext } from "react";
import type { ApiError } from "@/lib/api";
import type { BatteryParams, ForecastRun, TelemetryRow } from "@/lib/types";

export type ForecastInput = (
  | { kind: "upload"; file: File; battery?: BatteryParams }
  | { kind: "manual"; rows: TelemetryRow[]; battery?: BatteryParams }
  | { kind: "sample" }
) & { stay?: boolean };

export interface ActiveRunState {
  runId: string | null;
  run: ForecastRun | undefined;
  isLoading: boolean;
  error: ApiError | null;
  select: (id: string) => void;
  forecast: (input: ForecastInput) => void;
  isForecasting: boolean;
  lastError: ApiError | null;
}

export const ActiveRunContext = createContext<ActiveRunState | null>(null);

export function useActiveRun(): ActiveRunState {
  const context = useContext(ActiveRunContext);
  if (!context) throw new Error("useActiveRun must be used inside ActiveRunProvider");
  return context;
}
