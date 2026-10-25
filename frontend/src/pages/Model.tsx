import type { EChartsOption } from "echarts";
import { CheckCircle2, CircleSlash } from "lucide-react";
import { type ReactNode, useMemo } from "react";
import { Chart } from "@/components/Chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelCard } from "@/hooks/queries";
import { type ChartColors, useChartColors } from "@/hooks/useChartColors";
import { useTheme } from "@/hooks/useTheme";
import type { ModelCard } from "@/lib/types";
import { cn } from "@/lib/utils";

const SERIES_1 = { light: "#2a78d6", dark: "#3987e5" };
const SERIES_2 = { light: "#eb6834", dark: "#d95926" };

function base(c: ChartColors): EChartsOption {
  return {
    animationDuration: 300,
    aria: { enabled: true },
    textStyle: { fontFamily: "Inter Variable, system-ui, sans-serif", color: c.fgMuted },
    grid: { left: 52, right: 16, top: 36, bottom: 36 },
    tooltip: {
      trigger: "axis",
      backgroundColor: c.surface,
      borderColor: c.border,
      textStyle: { color: c.fg, fontSize: 12 },
    },
    legend: { top: 0, right: 0, textStyle: { color: c.fgMuted }, itemWidth: 14, itemHeight: 8 },
  };
}

function axis(c: ChartColors, extra: object = {}) {
  return {
    axisLine: { lineStyle: { color: c.chartAxis } },
    axisTick: { show: false },
    axisLabel: { color: c.fgSubtle, fontFamily: "JetBrains Mono Variable" },
    splitLine: { lineStyle: { color: c.chartGrid } },
    nameTextStyle: { color: c.fgSubtle },
    ...extra,
  };
}

function useOptions(card: ModelCard | undefined, c: ChartColors, dark: boolean) {
  return useMemo(() => {
    if (!card) return null;
    const s1 = dark ? SERIES_1.dark : SERIES_1.light;
    const s2 = dark ? SERIES_2.dark : SERIES_2.light;
    const knee = card.feature_spec.cooling_base_c;
    const temps = card.cooling_curve.map((p) => p.temp_c);
    const tempMin = Math.floor(Math.min(...temps) / 5) * 5;
    const tempMax = Math.ceil(Math.max(...temps) / 5) * 5;

    const profile: EChartsOption = {
      ...base(c),
      xAxis: axis(c, {
        type: "category",
        data: card.hourly_profile.map((p) => String(p.hour).padStart(2, "0")),
      }),
      yAxis: axis(c, { type: "value", name: "kW" }),
      series: [
        {
          name: "q25",
          type: "line",
          stack: "iqr",
          data: card.hourly_profile.map((p) => p.q25_kw),
          symbol: "none",
          lineStyle: { opacity: 0 },
          tooltip: { show: false },
        },
        {
          name: "Interquartile range",
          type: "line",
          stack: "iqr",
          data: card.hourly_profile.map((p) => p.q75_kw - p.q25_kw),
          symbol: "none",
          lineStyle: { opacity: 0 },
          itemStyle: { color: s1, opacity: 0.4 },
          areaStyle: { color: s1, opacity: 0.18 },
          tooltip: { show: false },
        },
        {
          name: "Mean demand",
          type: "line",
          data: card.hourly_profile.map((p) => p.mean_kw),
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { width: 2, color: s1 },
          itemStyle: { color: s1 },
        },
      ],
      legend: { ...(base(c).legend as object), data: ["Mean demand", "Interquartile range"] },
    };

    const cooling: EChartsOption = {
      ...base(c),
      tooltip: {
        ...(base(c).tooltip as object),
        trigger: "item",
        formatter: (p: unknown) => {
          const v = (p as { value: [number, number] }).value;
          return `${v[0].toFixed(1)} °C: ${v[1].toFixed(1)} kW above hourly mean`;
        },
      },
      xAxis: axis(c, { type: "value", name: "°C", min: tempMin, max: tempMax }),
      yAxis: axis(c, { type: "value", name: "kW vs hourly mean" }),
      series: [
        {
          name: "1 °C bin mean",
          type: "line",
          data: card.cooling_curve.map((p) => [p.temp_c, p.mean_adjusted_kw]),
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { width: 2, color: s2 },
          itemStyle: { color: s2 },
          markLine: {
            silent: true,
            symbol: "none",
            data: [
              {
                xAxis: knee,
                lineStyle: { color: c.fgSubtle, type: "dashed" },
                label: { formatter: `knee ${knee} °C`, color: c.fgMuted },
              },
            ],
          },
        },
      ],
    };

    const holdout: EChartsOption = {
      ...base(c),
      xAxis: axis(c, {
        type: "category",
        data: card.holdout_series.map((p) => p.timestamp.slice(5)),
        axisLabel: { color: c.fgSubtle, interval: 23, fontFamily: "JetBrains Mono Variable" },
      }),
      yAxis: axis(c, { type: "value", name: "kW" }),
      series: [
        {
          name: "Actual",
          type: "line",
          data: card.holdout_series.map((p) => p.actual_kw),
          symbol: "none",
          lineStyle: { width: 1.5, color: s1 },
          itemStyle: { color: s1 },
        },
        {
          name: "Predicted",
          type: "line",
          data: card.holdout_series.map((p) => p.predicted_kw),
          symbol: "none",
          lineStyle: { width: 1.5, color: s2 },
          itemStyle: { color: s2 },
        },
      ],
    };

    const values = card.holdout_scatter.flat();
    const lo = Math.floor(Math.min(...values) / 50) * 50;
    const hi = Math.ceil(Math.max(...values) / 50) * 50;
    const scatter: EChartsOption = {
      ...base(c),
      legend: undefined,
      grid: { left: 52, right: 16, top: 16, bottom: 40 },
      tooltip: {
        ...(base(c).tooltip as object),
        trigger: "item",
        formatter: (p: unknown) => {
          const v = (p as { value: [number, number] }).value;
          return `actual ${v[0]} kW · predicted ${v[1]} kW`;
        },
      },
      xAxis: axis(c, {
        type: "value",
        name: "actual kW",
        min: lo,
        max: hi,
        nameLocation: "middle",
        nameGap: 26,
      }),
      yAxis: axis(c, { type: "value", name: "predicted kW", min: lo, max: hi }),
      series: [
        {
          type: "scatter",
          data: card.holdout_scatter,
          symbolSize: 5,
          itemStyle: { color: s1, opacity: 0.45 },
        },
        {
          type: "line",
          data: [
            [lo, lo],
            [hi, hi],
          ],
          symbol: "none",
          silent: true,
          lineStyle: { color: c.fgSubtle, type: "dashed", width: 1 },
          tooltip: { show: false },
        },
      ],
    };
    return { profile, cooling, holdout, scatter };
  }, [card, c, dark]);
}

function ChartCard({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {note && <span className="text-xs text-fg-muted">{note}</span>}
      </CardHeader>
      <CardContent className="px-2 pb-2 pt-3">{children}</CardContent>
    </Card>
  );
}

const pretty = (name: string) => name.replace(/_/g, " ");

export default function ModelPage() {
  const card = useModelCard();
  const colors = useChartColors();
  const [theme] = useTheme();
  const options = useOptions(card.data, colors, theme === "dark");

  if (card.isLoading) return <Skeleton className="h-[600px] w-full" />;
  if (card.error || !card.data || !options) {
    return (
      <div className="rounded-lg border bg-surface p-8 text-center">
        <p className="text-sm text-fg-muted">The model card could not be loaded: {card.error?.message}</p>
        <Button className="mt-3" onClick={() => void card.refetch()}>
          Retry
        </Button>
      </div>
    );
  }
  const m = card.data;
  const best = Math.min(...m.candidates.map((x) => x.cv_mean));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-lg font-semibold tracking-tight">Model card</h1>
          <p className="text-sm text-fg-muted">
            {m.algorithm} on hour-of-day and degree-day features, trained on{" "}
            {m.training.rows.toLocaleString()} hourly rows ({m.training.start} to {m.training.end}) and
            published as a QuickML endpoint.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="grid">
            CV RMSE <span className="num">{m.validation_rmse_kw.toFixed(2)} kW</span>
          </Badge>
          <Badge tone="storage">
            Holdout RMSE <span className="num">{m.holdout_rmse_kw.toFixed(2)} kW</span>
          </Badge>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Why this model</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>{m.why}</p>
            <p className="text-fg-muted">{m.selection_rule}</p>
            <ul className="space-y-1.5">
              {m.features.map((f) => (
                <li key={f.name} className="flex gap-2">
                  <span className="w-44 shrink-0 font-mono text-xs text-fg">{f.name}</span>
                  <span className="text-fg-muted">{f.description}</span>
                </li>
              ))}
            </ul>
            <p className="text-fg-muted">
              Cooling slope <span className="num text-fg">{m.coefficients.cdd?.toFixed(2)} kW per °C</span>{" "}
              above <span className="num text-fg">{m.feature_spec.cooling_base_c} °C</span>.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Time-ordered cross-validation</CardTitle>
            <span className="text-xs text-fg-muted">{m.training.n_splits} expanding folds, RMSE kW</span>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-xs">
              <thead className="text-fg-muted">
                <tr className="border-b">
                  <th className="px-4 py-2 font-medium">Model</th>
                  {m.candidates[0]?.cv_folds.map((_, i) => (
                    <th key={i} className="px-2 py-2 text-right font-medium">
                      F{i + 1}
                    </th>
                  ))}
                  <th className="px-2 py-2 text-right font-medium">Mean</th>
                  <th className="px-2 py-2 text-right font-medium">Holdout</th>
                  <th className="px-4 py-2 font-medium">Extrapolates</th>
                </tr>
              </thead>
              <tbody className="num">
                {[...m.candidates]
                  .sort((a, b) => a.cv_mean - b.cv_mean)
                  .map((cand) => (
                    <tr
                      key={cand.name}
                      className={cn("border-b last:border-b-0", cand.name === m.selected && "bg-grid-soft")}
                    >
                      <td className="px-4 py-1.5 font-sans">
                        {pretty(cand.name)}
                        {cand.name === m.selected && (
                          <Badge tone="grid" className="ml-2">
                            selected
                          </Badge>
                        )}
                      </td>
                      {cand.cv_folds.map((fold, i) => (
                        <td key={i} className="px-2 py-1.5 text-right">
                          {fold.toFixed(2)}
                        </td>
                      ))}
                      <td
                        className={cn(
                          "px-2 py-1.5 text-right font-semibold",
                          cand.cv_mean === best && "text-storage",
                        )}
                      >
                        {cand.cv_mean.toFixed(2)}
                      </td>
                      <td className="px-2 py-1.5 text-right">{cand.holdout_rmse.toFixed(2)}</td>
                      <td className="px-4 py-1.5">
                        {cand.extrapolates ? (
                          <CheckCircle2 className="size-4 text-storage" aria-label="yes" />
                        ) : (
                          <CircleSlash className="size-4 text-fg-subtle" aria-label="no" />
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <p className="border-t px-4 py-2 text-xs text-fg-muted">
            Optional terms tested (CV mean):{" "}
            {Object.entries(m.optional_terms_cv_mean)
              .map(([k, v]) => `${pretty(k)} ${v.toFixed(2)}`)
              .join(" · ")}
            . None beat the base model, so none are used.
          </p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <ChartCard title="Predicted vs actual, holdout" note="last 7 days of the time-ordered holdout">
          <Chart option={options.holdout} style={{ height: 300 }} />
        </ChartCard>
        <ChartCard title="Holdout scatter" note={`RMSE ${m.holdout_rmse_kw.toFixed(2)} kW`}>
          <Chart option={options.scatter} style={{ height: 300 }} />
        </ChartCard>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Demand by hour of day" note="training data">
          <Chart option={options.profile} style={{ height: 280 }} />
        </ChartCard>
        <ChartCard title="Cooling knee" note="demand minus hourly mean, by temperature">
          <Chart option={options.cooling} style={{ height: 280 }} />
        </ChartCard>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Limitations</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
            {m.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
