import type ReactEChartsCore from "echarts-for-react/lib/core";
import { type Ref, useImperativeHandle, useMemo, useRef } from "react";
import { Chart } from "@/components/Chart";
import { useChartColors } from "@/hooks/useChartColors";
import { buildDemandOption } from "@/lib/charts/demand";
import type { AppConfig, Hour } from "@/lib/types";

export interface DemandChartHandle {
  toPng: () => string | null;
}

interface DemandChartProps {
  hours: Hour[];
  config: AppConfig;
  rmse: number;
  reserveSocPct: number;
  height?: number;
  ref?: Ref<DemandChartHandle>;
}

export function DemandChart({ hours, config, rmse, reserveSocPct, height = 420, ref }: DemandChartProps) {
  const colors = useChartColors();
  const chartRef = useRef<ReactEChartsCore>(null);
  const option = useMemo(
    () => buildDemandOption(hours, config, rmse, reserveSocPct, colors),
    [hours, config, rmse, reserveSocPct, colors],
  );
  useImperativeHandle(ref, () => ({
    toPng: () =>
      chartRef.current?.getEchartsInstance().getDataURL({ pixelRatio: 2, backgroundColor: colors.surface }) ??
      null,
  }));
  return (
    <Chart
      ref={chartRef}
      option={option}
      style={{ height }}
      ariaLabel="Predicted demand with grid mode bands, thresholds and battery state of charge"
    />
  );
}
