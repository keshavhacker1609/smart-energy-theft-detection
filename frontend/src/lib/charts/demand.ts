import type { EChartsOption } from "echarts";
import type { ChartColors } from "@/hooks/useChartColors";
import { fmtDayClock, MODE_LABEL, parseTs } from "@/lib/format";
import { modeSegments } from "@/lib/run";
import type { AppConfig, Hour } from "@/lib/types";

const HOUR_MS = 3_600_000;

/** Breaks a line wherever consecutive points are more than an hour apart, so gaps are not drawn over. */
function withGaps(points: [number, number | null][]): [number, number | null][] {
  const out: [number, number | null][] = [];
  points.forEach((point, i) => {
    const previous = points[i - 1];
    if (previous && point[0] - previous[0] > HOUR_MS * 1.5) out.push([previous[0] + HOUR_MS, null]);
    out.push(point);
  });
  return out;
}

function peakWindows(hours: Hour[], config: AppConfig): [number, number][] {
  const days = new Map<string, number>();
  for (const hour of hours) {
    const at = parseTs(hour.timestamp);
    if (at.getHours() >= config.peak_start_hour && at.getHours() <= config.peak_end_hour) {
      const day = new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();
      days.set(String(day), day);
    }
  }
  return [...days.values()].map((day) => [
    day + (config.peak_start_hour - 0.5) * HOUR_MS,
    day + (config.peak_end_hour + 0.5) * HOUR_MS,
  ]);
}

function tooltipHtml(hour: Hour, rmse: number, c: ChartColors): string {
  const modeColor = hour.mode === "RENEWABLE_STORAGE" ? c.storage : c.grid;
  const rows = [
    [
      "Predicted",
      `${hour.predicted_kw.toFixed(1)} kW <span style="color:${c.fgSubtle}">± ${rmse.toFixed(1)}</span>`,
    ],
    ...(hour.actual_kw !== null ? [["Actual", `${hour.actual_kw.toFixed(1)} kW`]] : []),
    ["Battery SoC", `${hour.soc_pct.toFixed(1)}%`],
    ["Temperature", `${hour.ambient_temp_c.toFixed(1)} °C`],
  ];
  const reasons = hour.reasons.map((r) => `<li>${r}</li>`).join("");
  return `
    <div style="font-family:Inter Variable,system-ui;min-width:220px">
      <div style="font-weight:600;margin-bottom:6px">${fmtDayClock(hour.timestamp)}</div>
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
        <span style="width:8px;height:8px;border-radius:2px;background:${modeColor}"></span>
        ${MODE_LABEL[hour.mode]}${hour.overload ? ` <b style="color:${c.overload}">· Critical overload</b>` : ""}
      </div>
      <table style="width:100%;font-variant-numeric:tabular-nums">${rows
        .map(
          ([k, v]) =>
            `<tr><td style="color:${c.fgMuted};padding-right:12px">${k}</td><td style="text-align:right">${v}</td></tr>`,
        )
        .join("")}</table>
      <ul style="margin:8px 0 0;padding-left:14px;color:${c.fgMuted};max-width:280px;white-space:normal">${reasons}</ul>
    </div>`;
}

export function buildDemandOption(
  hours: Hour[],
  config: AppConfig,
  rmse: number,
  reserveSocPct: number,
  c: ChartColors,
): EChartsOption {
  const times = hours.map((h) => parseTs(h.timestamp).getTime());
  const at = (i: number) => times[i] ?? 0;
  const predicted = withGaps(hours.map((h, i) => [at(i), h.predicted_kw]));
  const lower = withGaps(hours.map((h, i) => [at(i), h.predicted_kw - rmse]));
  const band = withGaps(hours.map((_, i) => [at(i), 2 * rmse]));
  const hasActual = hours.some((h) => h.actual_kw !== null);
  const top = Math.max(config.overload_threshold_kw, ...hours.map((h) => h.predicted_kw + rmse)) * 1.14;
  const yMax = Math.ceil(top / 20) * 20;
  const xMin = (times[0] ?? 0) - HOUR_MS / 2;
  const xMax = (times.at(-1) ?? 0) + HOUR_MS / 2;
  const byTime = new Map(hours.map((h, i) => [times[i], h]));

  const axisCommon = {
    type: "time" as const,
    min: xMin,
    max: xMax,
    axisLine: { lineStyle: { color: c.chartAxis } },
    axisTick: { show: false },
    splitLine: { show: false },
  };
  const valueAxisCommon = {
    type: "value" as const,
    axisLine: { show: false },
    axisLabel: { color: c.fgSubtle, fontFamily: "JetBrains Mono Variable" },
    splitLine: { lineStyle: { color: c.chartGrid } },
    nameTextStyle: { color: c.fgSubtle, align: "left" as const },
  };

  return {
    animationDuration: 400,
    aria: { enabled: true },
    textStyle: { fontFamily: "Inter Variable, system-ui, sans-serif" },
    axisPointer: { link: [{ xAxisIndex: "all" }], lineStyle: { color: c.fgSubtle } },
    tooltip: {
      trigger: "axis",
      backgroundColor: c.surface,
      borderColor: c.border,
      textStyle: { color: c.fg, fontSize: 12 },
      extraCssText: "box-shadow:0 8px 24px rgba(0,0,0,.25);border-radius:8px;",
      formatter: (params) => {
        const list = Array.isArray(params) ? params : [params];
        const value = list[0]?.value as [number, number] | undefined;
        const hour = value ? byTime.get(value[0]) : undefined;
        return hour ? tooltipHtml(hour, rmse, c) : "";
      },
    },
    grid: [
      { left: 52, right: 16, top: 16, height: "58%" },
      { left: 52, right: 16, top: "76%", bottom: 28 },
    ],
    xAxis: [
      { ...axisCommon, gridIndex: 0, axisLabel: { show: false } },
      {
        ...axisCommon,
        gridIndex: 1,
        axisLabel: { color: c.fgSubtle, fontFamily: "JetBrains Mono Variable", hideOverlap: true },
      },
    ],
    yAxis: [
      { ...valueAxisCommon, gridIndex: 0, min: 0, max: yMax, name: "kW" },
      { ...valueAxisCommon, gridIndex: 1, min: 0, max: 100, interval: 50, name: "SoC %" },
    ],
    series: [
      {
        name: "band-lower",
        type: "line",
        data: lower,
        stack: "band",
        symbol: "none",
        lineStyle: { opacity: 0 },
        tooltip: { show: false },
        silent: true,
        markArea: {
          silent: true,
          data: peakWindows(hours, config).map(([start, end]) => [
            {
              xAxis: start,
              yAxis: yMax * 0.94,
              itemStyle: { color: c.peak, borderColor: c.border, borderWidth: 1 },
              label: {
                show: true,
                position: "inside",
                color: c.fgMuted,
                fontSize: 11,
                formatter: `Peak window ${config.peak_start_hour}–${config.peak_end_hour}`,
              },
            },
            { xAxis: end, yAxis: yMax },
          ]),
        },
      },
      {
        name: `±${rmse.toFixed(1)} kW validation RMSE`,
        type: "line",
        data: band,
        stack: "band",
        symbol: "none",
        lineStyle: { opacity: 0 },
        areaStyle: { color: c.fgSubtle, opacity: 0.16 },
        silent: true,
      },
      {
        name: "Predicted demand",
        type: "line",
        data: predicted,
        symbol: "circle",
        symbolSize: 5,
        showSymbol: false,
        lineStyle: { width: 2, color: c.fg },
        itemStyle: { color: c.fg },
        z: 5,
        markArea: {
          silent: true,
          data: modeSegments(hours).map((segment) => [
            {
              xAxis: segment.start.getTime(),
              itemStyle: { color: segment.mode === "RENEWABLE_STORAGE" ? c.storageSoft : c.gridSoft },
            },
            { xAxis: segment.end.getTime() },
          ]),
        },
        markLine: {
          silent: true,
          symbol: "none",
          data: [
            {
              yAxis: config.storage_threshold_kw,
              lineStyle: { color: c.fgSubtle, type: "dashed" },
              label: {
                formatter: `${config.storage_threshold_kw} kW storage`,
                position: "insideStartTop",
                color: c.fgMuted,
              },
            },
            {
              yAxis: config.overload_threshold_kw,
              lineStyle: { color: c.overload, type: "dashed" },
              label: {
                formatter: `${config.overload_threshold_kw} kW overload`,
                position: "insideStartTop",
                color: c.fgMuted,
              },
            },
          ],
        },
      },
      ...(hasActual
        ? [
            {
              name: "Actual demand",
              type: "line" as const,
              data: withGaps(hours.map((h, i) => [at(i), h.actual_kw])),
              symbol: "none",
              connectNulls: false,
              lineStyle: { width: 1.5, type: "dashed" as const, color: c.fgMuted },
              z: 4,
            },
          ]
        : []),
      {
        name: "Critical overload",
        type: "scatter",
        data: hours.filter((h) => h.overload).map((h) => [parseTs(h.timestamp).getTime(), h.predicted_kw]),
        symbol: "triangle",
        symbolSize: 13,
        itemStyle: { color: c.overload, borderColor: c.surface, borderWidth: 2 },
        z: 6,
      },
      {
        name: "Battery SoC",
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: withGaps(hours.map((h, i) => [at(i), h.soc_pct])),
        symbol: "none",
        lineStyle: { width: 2, color: c.storage },
        areaStyle: { color: c.storage, opacity: 0.14 },
        markLine: {
          silent: true,
          symbol: "none",
          data: [
            {
              yAxis: reserveSocPct,
              lineStyle: { color: c.warning, type: "dashed" },
              label: { formatter: `reserve ${reserveSocPct}%`, position: "insideEndTop", color: c.fgMuted },
            },
          ],
        },
      },
    ],
  };
}
