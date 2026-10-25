import { useMemo } from "react";
import { useTheme } from "./useTheme";

export interface ChartColors {
  surface: string;
  fg: string;
  fgMuted: string;
  fgSubtle: string;
  grid: string;
  gridSoft: string;
  storage: string;
  storageSoft: string;
  overload: string;
  warning: string;
  chartGrid: string;
  chartAxis: string;
  peak: string;
  border: string;
}

const VARS: Record<keyof ChartColors, string> = {
  surface: "--surface",
  fg: "--fg",
  fgMuted: "--fg-muted",
  fgSubtle: "--fg-subtle",
  grid: "--grid",
  gridSoft: "--grid-soft",
  storage: "--storage",
  storageSoft: "--storage-soft",
  overload: "--overload",
  warning: "--warning-fill",
  chartGrid: "--chart-grid",
  chartAxis: "--chart-axis",
  peak: "--peak",
  border: "--border-strong",
};

/** Chart colours resolved from the active theme's CSS tokens, so charts and UI never drift. */
export function useChartColors(): ChartColors {
  const [theme] = useTheme();
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    const entries = Object.entries(VARS).map(([key, name]) => [key, style.getPropertyValue(name).trim()]);
    return Object.fromEntries(entries) as ChartColors;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);
}
