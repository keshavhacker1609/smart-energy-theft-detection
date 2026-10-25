import { BatteryWarning, TriangleAlert } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { fmtClock, fmtDayClock, MODE_LABEL } from "@/lib/format";
import type { Hour } from "@/lib/types";
import { cn } from "@/lib/utils";

function HourDetail({ hour }: { hour: Hour }) {
  return (
    <div className="space-y-1.5">
      <div className="font-semibold">{fmtDayClock(hour.timestamp)}</div>
      <div className="num">
        {hour.predicted_kw.toFixed(1)} kW · {MODE_LABEL[hour.mode]}
      </div>
      <ul className="list-disc space-y-0.5 pl-4 text-fg-muted">
        {hour.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
        {hour.reserve_low && <li>BATTERY_RESERVE_LOW: SoC {hour.soc_pct.toFixed(1)}% at reserve</li>}
        {hour.imputed.length > 0 && <li>Imputed inputs: {hour.imputed.join(", ")}</li>}
      </ul>
    </div>
  );
}

export function DispatchTimeline({ hours }: { hours: Hour[] }) {
  return (
    <div>
      <ol
        className="grid grid-cols-6 gap-1 sm:grid-cols-12 lg:grid-cols-24"
        aria-label="Hourly dispatch signals"
      >
        {hours.map((hour) => {
          const storage = hour.mode === "RENEWABLE_STORAGE";
          return (
            <li key={hour.timestamp}>
              <Tooltip content={<HourDetail hour={hour} />}>
                <button
                  type="button"
                  className={cn(
                    "relative flex h-14 w-full flex-col items-center justify-between rounded-md border py-1.5 transition-transform hover:-translate-y-0.5",
                    storage ? "border-storage/40 bg-storage-soft" : "border-grid/40 bg-grid-soft",
                    hour.overload && "ring-2 ring-overload ring-offset-1 ring-offset-surface",
                  )}
                  aria-label={`${fmtDayClock(hour.timestamp)}: ${hour.predicted_kw.toFixed(1)} kW, ${MODE_LABEL[hour.mode]}${hour.overload ? ", critical overload" : ""}${hour.reserve_low ? ", battery reserve low" : ""}`}
                >
                  <span className="num text-[11px] text-fg-muted">{fmtClock(hour.timestamp)}</span>
                  <span className="flex h-4 items-center gap-0.5">
                    {hour.overload && <TriangleAlert className="size-3.5 text-overload" aria-hidden />}
                    {hour.reserve_low && <BatteryWarning className="size-3.5 text-warning" aria-hidden />}
                  </span>
                  <span
                    className={cn("h-1 w-5 rounded-full", storage ? "bg-storage" : "bg-grid")}
                    aria-hidden
                  />
                </button>
              </Tooltip>
            </li>
          );
        })}
      </ol>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-grid" aria-hidden /> Main grid
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-storage" aria-hidden /> Renewable storage
        </span>
        <span className="flex items-center gap-1.5">
          <TriangleAlert className="size-3.5 text-overload" aria-hidden /> Critical overload
        </span>
        <span className="flex items-center gap-1.5">
          <BatteryWarning className="size-3.5 text-warning" aria-hidden /> Battery at reserve
        </span>
      </div>
    </div>
  );
}
