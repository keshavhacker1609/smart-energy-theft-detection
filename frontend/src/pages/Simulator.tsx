import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { Loader2, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Chart } from "@/components/Chart";
import { DispatchTimeline } from "@/components/dashboard/DispatchTimeline";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { useConfig } from "@/hooks/queries";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useChartColors } from "@/hooks/useChartColors";
import { useDebounced } from "@/hooks/useDebounced";
import { api } from "@/lib/api";
import { buildDemandOption } from "@/lib/charts/demand";
import { fmtSigned, parseTs } from "@/lib/format";
import { windowHours } from "@/lib/run";
import type { BatteryParams, ScenarioDelta, TelemetryRow } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Scenario {
  offset: number;
  capacity: number;
  initialSoc: number;
}

function Control(props: {
  id: string;
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <label id={props.id} className="text-sm font-medium">
          {props.label}
        </label>
        <span className="num text-sm text-fg">{props.display}</span>
      </div>
      <Slider
        aria-labelledby={props.id}
        min={props.min}
        max={props.max}
        step={props.step}
        value={[props.value]}
        onValueChange={([value]) => value !== undefined && props.onChange(value)}
      />
      <div className="num flex justify-between text-[11px] text-fg-subtle">
        <span>{props.min}</span>
        <span>{props.max}</span>
      </div>
    </div>
  );
}

const DELTA_ITEMS: {
  key: keyof ScenarioDelta;
  label: string;
  unit: string;
  digits: number;
  worseWhenUp: boolean | null;
}[] = [
  { key: "overload_hours", label: "overload hours", unit: "", digits: 0, worseWhenUp: true },
  { key: "peak_kw", label: "peak demand", unit: " kW", digits: 1, worseWhenUp: true },
  { key: "storage_hours", label: "hours on storage", unit: "", digits: 0, worseWhenUp: null },
  { key: "reserve_low_hours", label: "hours at battery reserve", unit: "", digits: 0, worseWhenUp: true },
  {
    key: "grid_energy_avoided_kwh",
    label: "grid energy avoided",
    unit: " kWh",
    digits: 0,
    worseWhenUp: false,
  },
  { key: "min_soc_pct", label: "lowest SoC", unit: " pts", digits: 1, worseWhenUp: false },
];

export default function SimulatorPage() {
  const { run } = useActiveRun();
  const config = useConfig();
  const colors = useChartColors();
  const [scenario, setScenario] = useState<Scenario | null>(null);

  const baseline: Scenario | null = run
    ? { offset: 0, capacity: run.battery.capacity_kwh, initialSoc: run.battery.initial_soc_pct }
    : null;
  const current = scenario ?? baseline;
  const debounced = useDebounced(current, 350);

  const rows = useMemo<TelemetryRow[]>(
    () =>
      run
        ? windowHours(run).map((h) => ({
            timestamp: h.timestamp.replace("T", " "),
            ambient_temp_c: h.ambient_temp_c,
            humidity_pct: h.humidity_pct,
            solar_irradiance_wm2: h.solar_irradiance_wm2,
          }))
        : [],
    [run],
  );

  const simulation = useQuery({
    queryKey: ["simulate", run?.id, debounced],
    queryFn: () => {
      if (!run || !debounced) throw new Error("no run");
      const battery: BatteryParams = {
        ...run.battery,
        capacity_kwh: debounced.capacity,
        initial_soc_pct: debounced.initialSoc,
      };
      return api.simulate(rows, debounced.offset, battery);
    },
    enabled: Boolean(run && debounced),
    placeholderData: keepPreviousData,
  });

  const option = useMemo<EChartsOption | null>(() => {
    const data = simulation.data;
    if (!data || !config.data || !run) return null;
    const option = buildDemandOption(
      data.scenario.hours,
      config.data,
      run.model.validation_rmse_kw,
      run.battery.reserve_soc_pct,
      colors,
    );
    const baselineSeries = [
      {
        name: "Baseline demand",
        type: "line" as const,
        data: data.baseline.hours.map((h) => [parseTs(h.timestamp).getTime(), h.predicted_kw]),
        symbol: "none",
        lineStyle: { width: 1.5, type: "dashed" as const, color: colors.fgSubtle },
        z: 4,
      },
      {
        name: "Baseline SoC",
        type: "line" as const,
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: data.baseline.hours.map((h) => [parseTs(h.timestamp).getTime(), h.soc_pct]),
        symbol: "none",
        lineStyle: { width: 1.5, type: "dashed" as const, color: colors.fgSubtle },
      },
    ];
    return { ...option, series: [...(option.series as object[]), ...baselineSeries] } as EChartsOption;
  }, [simulation.data, config.data, run, colors]);

  if (!run || !current || !config.data) {
    return (
      <EmptyState
        title="Nothing to simulate yet"
        description="The what-if simulator perturbs the active forecast. Run a forecast first."
      />
    );
  }

  const [minOffset, maxOffset] = config.data.temperature_offset_range_c;
  const update = (patch: Partial<Scenario>) => setScenario({ ...current, ...patch });
  const delta = simulation.data?.delta;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">What-if simulator</h1>
        <p className="text-sm text-fg-muted">
          Re-forecasts the active 24-hour window through QuickML with shifted temperature and battery
          settings. Nothing is saved.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Scenario</CardTitle>
            <Button variant="ghost" size="sm" onClick={() => setScenario(null)} disabled={!scenario}>
              <RotateCcw /> Reset
            </Button>
          </CardHeader>
          <CardContent className="space-y-6">
            <Control
              id="sim-offset"
              label="Temperature offset"
              value={current.offset}
              display={fmtSigned(current.offset, 1, " °C")}
              min={minOffset}
              max={maxOffset}
              step={0.5}
              onChange={(offset) => update({ offset })}
            />
            <Control
              id="sim-capacity"
              label="Battery capacity"
              value={current.capacity}
              display={`${current.capacity.toFixed(0)} kWh`}
              min={100}
              max={2000}
              step={50}
              onChange={(capacity) => update({ capacity })}
            />
            <Control
              id="sim-soc"
              label="Initial state of charge"
              value={current.initialSoc}
              display={`${current.initialSoc.toFixed(0)}%`}
              min={0}
              max={100}
              step={5}
              onChange={(initialSoc) => update({ initialSoc })}
            />
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Change versus baseline</CardTitle>
              {simulation.isFetching && (
                <Loader2 className="size-4 animate-spin text-fg-muted" aria-label="Updating" />
              )}
            </CardHeader>
            <CardContent>
              {simulation.error ? (
                <p role="alert" className="text-sm text-overload">
                  {simulation.error.message}{" "}
                  <Button size="sm" variant="ghost" onClick={() => void simulation.refetch()}>
                    Retry
                  </Button>
                </p>
              ) : delta ? (
                <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {DELTA_ITEMS.map((item) => {
                    const value = delta[item.key];
                    const worse = item.worseWhenUp ? value > 0 : value < 0;
                    const neutral = item.worseWhenUp === null || Math.abs(value) < 10 ** -item.digits / 2;
                    return (
                      <li key={item.key} className="rounded-md border bg-raised/40 px-3 py-2">
                        <div
                          className={cn(
                            "num text-lg font-semibold",
                            !neutral && (worse ? "text-overload" : "text-storage"),
                          )}
                        >
                          {fmtSigned(value, item.digits, item.unit)}
                        </div>
                        <div className="text-xs text-fg-muted">{item.label}</div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <Skeleton className="h-24 w-full" />
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Scenario demand and state of charge</CardTitle>
              <span className="text-xs text-fg-muted">dashed: baseline</span>
            </CardHeader>
            <CardContent className="px-2 pb-2 pt-3">
              {option ? (
                <Chart option={option} style={{ height: 400 }} ariaLabel="Scenario demand against baseline" />
              ) : (
                <Skeleton className="h-[400px] w-full" />
              )}
            </CardContent>
          </Card>
          {simulation.data && (
            <Card>
              <CardHeader>
                <CardTitle>Scenario dispatch</CardTitle>
              </CardHeader>
              <CardContent>
                <DispatchTimeline hours={simulation.data.scenario.hours} />
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
