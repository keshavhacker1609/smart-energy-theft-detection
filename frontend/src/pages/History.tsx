import { RotateCw } from "lucide-react";
import { useNavigate } from "react-router";
import { ModeBadge } from "@/components/dashboard/StatusStrip";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRuns } from "@/hooks/queries";
import { useActiveRun } from "@/hooks/useActiveRun";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function HistoryPage() {
  const runs = useRuns();
  const { runId, select } = useActiveRun();
  const navigate = useNavigate();

  if (runs.isLoading) return <Skeleton className="h-96 w-full" />;
  if (runs.error) {
    return (
      <div className="rounded-lg border bg-surface p-8 text-center">
        <p className="text-sm text-fg-muted">History is unavailable: {runs.error.message}</p>
        <Button className="mt-3" onClick={() => void runs.refetch()}>
          <RotateCw /> Retry
        </Button>
      </div>
    );
  }
  if (!runs.data?.length) {
    return (
      <EmptyState
        title="No saved runs"
        description="Forecast runs are stored here as soon as they complete."
      />
    );
  }

  const open = (id: string) => {
    select(id);
    navigate("/");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Forecast runs</CardTitle>
        <span className="text-xs text-fg-muted">
          {runs.data.length} most recent · select a run to load it
        </span>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="text-xs text-fg-muted">
            <tr className="border-b">
              <th className="px-4 py-2 font-medium">Created</th>
              <th className="px-2 py-2 font-medium">Source</th>
              <th className="px-2 py-2 text-right font-medium">Rows</th>
              <th className="px-2 py-2 font-medium">Window start</th>
              <th className="px-2 py-2 font-medium">Starting mode</th>
              <th className="px-2 py-2 text-right font-medium">Peak</th>
              <th className="px-2 py-2 text-right font-medium">Overload h</th>
              <th className="px-4 py-2 text-right font-medium">Transitions</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.map((item) => (
              <tr
                key={item.id}
                className={cn(
                  "cursor-pointer border-b last:border-b-0 hover:bg-raised focus-within:bg-raised",
                  item.id === runId && "bg-grid-soft",
                )}
                onClick={() => open(item.id)}
              >
                <td className="px-4 py-2">
                  <button
                    type="button"
                    className="num text-left"
                    onClick={(event) => {
                      event.stopPropagation();
                      open(item.id);
                    }}
                  >
                    {fmtDateTime(item.created_at)}
                  </button>
                </td>
                <td className="px-2 py-2">
                  <span className="flex items-center gap-2">
                    <Badge>{item.source}</Badge>
                    <span className="max-w-[180px] truncate text-fg-muted">
                      {item.filename ?? "manual entry"}
                    </span>
                  </span>
                </td>
                <td className="num px-2 py-2 text-right">{item.rows}</td>
                <td className="num px-2 py-2">{fmtDateTime(item.window_start)}</td>
                <td className="px-2 py-2">
                  <ModeBadge mode={item.current_mode} />
                </td>
                <td className="num px-2 py-2 text-right">{item.peak_kw.toFixed(1)} kW</td>
                <td className={cn("num px-2 py-2 text-right", item.overload_hours > 0 && "text-overload")}>
                  {item.overload_hours}
                </td>
                <td className="num px-4 py-2 text-right">{item.transitions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
