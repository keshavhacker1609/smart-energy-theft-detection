import { CloudOff, Download, FileImage, RotateCw } from "lucide-react";
import { useMemo, useRef } from "react";
import { DemandChart, type DemandChartHandle } from "@/components/dashboard/DemandChart";
import { DispatchTimeline } from "@/components/dashboard/DispatchTimeline";
import { AlertBanner } from "@/components/dashboard/AlertBanner";
import { KpiCards } from "@/components/dashboard/KpiCards";
import { StatusStrip } from "@/components/dashboard/StatusStrip";
import { SystemLog } from "@/components/dashboard/SystemLog";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useConfig } from "@/hooks/queries";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { fmtDateTime, fmtDayClock } from "@/lib/format";
import { hoursToCsv, windowHours } from "@/lib/run";
import { downloadBlob } from "@/lib/utils";

function DashboardSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading forecast">
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-[420px] w-full" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { run, isLoading, error } = useActiveRun();
  const config = useConfig();
  const chartRef = useRef<DemandChartHandle>(null);
  const compact = useMediaQuery("(max-width: 640px)");
  const hours = useMemo(() => (run ? windowHours(run) : []), [run]);

  if (isLoading || config.isLoading) return <DashboardSkeleton />;

  if (config.error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border bg-surface px-6 py-16 text-center">
        <CloudOff className="size-6 text-overload" aria-hidden />
        <p className="font-semibold">Cannot reach the forecast API</p>
        <p className="max-w-md text-sm text-fg-muted">{config.error.message}</p>
        <Button onClick={() => void config.refetch()}>
          <RotateCw /> Retry
        </Button>
      </div>
    );
  }

  if (!run || !config.data) {
    const missing = error?.status === 404;
    return (
      <EmptyState
        title={missing ? "The last viewed run is no longer stored" : "No forecast yet"}
        description="Upload a telemetry CSV or enter readings manually to forecast the next 24 hours, or run the sample data through the live pipeline."
      />
    );
  }

  const exportCsv = () =>
    downloadBlob(
      new Blob([hoursToCsv(run.hours)], { type: "text/csv" }),
      `forecast-${run.id.slice(0, 8)}.csv`,
    );
  const exportPng = () => {
    const url = chartRef.current?.toPng();
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    link.download = `forecast-${run.id.slice(0, 8)}.png`;
    link.click();
  };

  return (
    <div className="space-y-4">
      <AlertBanner run={run} />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Next {run.summary.window_hours} hours</h1>
          <p className="text-sm text-fg-muted">
            <span className="num">
              {fmtDayClock(run.summary.window_start)} – {fmtDayClock(run.summary.window_end)}
            </span>{" "}
            · {run.filename ?? "manual entry"} · {run.hours.length} rows forecast · run{" "}
            <span className="num">{run.id.slice(0, 8)}</span> at {fmtDateTime(run.created_at)}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={exportCsv}>
            <Download /> CSV
          </Button>
          <Button size="sm" onClick={exportPng}>
            <FileImage /> PNG
          </Button>
        </div>
      </div>
      {!run.persisted && (
        <p className="rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-sm">
          This forecast was not saved to history: {run.storage_warning ?? "storage unavailable"}. Export it as
          CSV to keep a copy.
        </p>
      )}
      <StatusStrip run={run} />
      <Card>
        <CardHeader>
          <CardTitle>Predicted demand and dispatch</CardTitle>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 bg-fg" aria-hidden /> Predicted
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-4 rounded-sm bg-fg-subtle/30" aria-hidden /> ±{" "}
              {run.model.validation_rmse_kw.toFixed(1)} kW
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-grid/40" aria-hidden /> Main grid
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm bg-storage/40" aria-hidden /> Storage
            </span>
            <span className="flex items-center gap-1.5">
              <span className="text-overload" aria-hidden>
                ▲
              </span>{" "}
              Overload
            </span>
          </div>
        </CardHeader>
        <CardContent className="px-2 pb-2 pt-3">
          <DemandChart
            ref={chartRef}
            hours={hours}
            config={config.data}
            rmse={run.model.validation_rmse_kw}
            reserveSocPct={run.battery.reserve_soc_pct}
            height={compact ? 360 : 440}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Dispatch timeline</CardTitle>
          <span className="text-xs text-fg-muted">Hover or focus an hour for the rules that fired</span>
        </CardHeader>
        <CardContent>
          <DispatchTimeline hours={hours} />
        </CardContent>
      </Card>
      <KpiCards summary={run.summary} />
      <Card>
        <CardHeader>
          <CardTitle>System log</CardTitle>
          <span className="text-xs text-fg-muted">{run.events.length} events</span>
        </CardHeader>
        <SystemLog events={run.events} />
      </Card>
    </div>
  );
}
