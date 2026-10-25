import { ArrowRightLeft, BatteryMedium, Cable, Leaf, Siren, Target } from "lucide-react";
import type { ReactNode } from "react";
import { fmtDayClock, MODE_LABEL } from "@/lib/format";
import type { ForecastRun, GridMode } from "@/lib/types";
import { cn } from "@/lib/utils";

function Cell({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5 px-4 py-3", className)}>
      <span className="text-[11px] font-medium uppercase tracking-wider text-fg-subtle">{label}</span>
      {children}
    </div>
  );
}

export function ModeBadge({ mode, large = false }: { mode: GridMode; large?: boolean }) {
  const storage = mode === "RENEWABLE_STORAGE";
  const Icon = storage ? Leaf : Cable;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-md border font-semibold",
        storage ? "border-storage/40 bg-storage-soft text-storage" : "border-grid/40 bg-grid-soft text-grid",
        large ? "px-3 py-1.5 text-base" : "px-2 py-0.5 text-xs",
      )}
    >
      <Icon className={large ? "size-5" : "size-3.5"} aria-hidden />
      {MODE_LABEL[mode]}
    </span>
  );
}

function SocGauge({ value, reserve }: { value: number; reserve: number }) {
  const low = value <= reserve + 0.5;
  return (
    <div className="flex items-center gap-3">
      <div
        className="relative h-2.5 w-28 overflow-hidden rounded-full bg-raised"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value)}
        aria-label="Battery state of charge"
      >
        <div
          className={cn("absolute inset-y-0 left-0 rounded-full", low ? "bg-warning-fill" : "bg-storage")}
          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        />
        <div className="absolute inset-y-0 w-px bg-fg-subtle" style={{ left: `${reserve}%` }} aria-hidden />
      </div>
      <span className="num text-lg font-semibold">{value.toFixed(0)}%</span>
    </div>
  );
}

export function StatusStrip({ run }: { run: ForecastRun }) {
  const { summary, hours, battery, model } = run;
  const alerts = summary.overload_hours + summary.reserve_low_hours;
  const firstHour = hours[0];
  return (
    <section
      aria-label="Current status"
      className="grid grid-cols-2 divide-border rounded-lg border bg-surface md:grid-cols-5 md:divide-x [&>*]:border-b md:[&>*]:border-b-0"
    >
      <Cell label={`Mode at ${fmtDayClock(summary.window_start)}`} className="col-span-2 md:col-span-1">
        <ModeBadge mode={summary.current_mode} large />
      </Cell>
      <Cell label="Next transition">
        {summary.next_transition_at && summary.next_transition_mode ? (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            <ArrowRightLeft className="size-4 text-fg-subtle" aria-hidden />
            <span className="num font-semibold">{fmtDayClock(summary.next_transition_at)}</span>
            <ModeBadge mode={summary.next_transition_mode} />
          </span>
        ) : (
          <span className="text-sm text-fg-muted">No change in window</span>
        )}
      </Cell>
      <Cell label="Active alerts">
        <span className={cn("flex items-center gap-2", alerts ? "text-overload" : "text-fg-muted")}>
          <Siren className="size-4" aria-hidden />
          <span className="num text-lg font-semibold">{alerts}</span>
          <span className="text-xs text-fg-muted">
            {summary.overload_hours} overload · {summary.reserve_low_hours} reserve
          </span>
        </span>
      </Cell>
      <Cell label="Battery SoC">
        <span className="flex items-center gap-2">
          <BatteryMedium className="size-4 text-fg-subtle" aria-hidden />
          <SocGauge value={firstHour?.soc_pct ?? battery.initial_soc_pct} reserve={battery.reserve_soc_pct} />
        </span>
      </Cell>
      <Cell label="Model">
        <span className="flex items-center gap-2 text-sm">
          <Target className="size-4 text-fg-subtle" aria-hidden />
          <span>
            RMSE <span className="num font-semibold">{model.validation_rmse_kw.toFixed(2)} kW</span>
          </span>
        </span>
        {summary.actual_rmse_kw !== null && (
          <span className="text-xs text-fg-muted">
            vs uploaded actuals: <span className="num">{summary.actual_rmse_kw.toFixed(2)} kW</span> (
            {summary.actual_rows} h)
          </span>
        )}
      </Cell>
    </section>
  );
}
