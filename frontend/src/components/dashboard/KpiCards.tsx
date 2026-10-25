import { ArrowRightLeft, Gauge, Leaf, PlugZap } from "lucide-react";
import type { ReactNode } from "react";
import { fmtDayClock } from "@/lib/format";
import type { Summary } from "@/lib/types";

function Kpi({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border bg-surface p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-fg-muted [&_svg]:size-4">
        {icon}
        {label}
      </div>
      <div className="num mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      <div className="mt-1 text-xs text-fg-subtle">{detail}</div>
    </div>
  );
}

export function KpiCards({ summary }: { summary: Summary }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Kpi
        icon={<Gauge aria-hidden />}
        label="Peak demand"
        value={`${summary.peak_kw.toFixed(1)} kW`}
        detail={`at ${fmtDayClock(summary.peak_at)}`}
      />
      <Kpi
        icon={<Leaf aria-hidden />}
        label="Hours on storage"
        value={`${summary.storage_hours} / ${summary.window_hours}`}
        detail={`${summary.grid_hours} h on main grid`}
      />
      <Kpi
        icon={<ArrowRightLeft aria-hidden />}
        label="Mode transitions"
        value={String(summary.transitions)}
        detail="switches between grid and storage"
      />
      <Kpi
        icon={<PlugZap aria-hidden />}
        label="Grid energy avoided"
        value={`${summary.grid_energy_avoided_kwh.toFixed(0)} kWh`}
        detail={`battery ends at ${summary.final_soc_pct.toFixed(0)}% SoC`}
      />
    </div>
  );
}
