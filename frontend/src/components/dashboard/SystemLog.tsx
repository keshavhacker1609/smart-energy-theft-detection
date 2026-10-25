import { CircleAlert, Info, OctagonAlert } from "lucide-react";
import { useState } from "react";
import { fmtDateTime, fmtDayClock } from "@/lib/format";
import type { LogEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "all" | "dispatch" | "ingest" | "alerts";

const ICONS = {
  info: <Info className="size-3.5 text-fg-subtle" aria-label="info" />,
  warning: <CircleAlert className="size-3.5 text-warning" aria-label="warning" />,
  critical: <OctagonAlert className="size-3.5 text-overload" aria-label="critical" />,
};

export function SystemLog({ events }: { events: LogEvent[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const shown = events.filter((event) => {
    if (filter === "all") return true;
    if (filter === "alerts") return event.level !== "info";
    return event.phase === filter;
  });
  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 border-b px-3 py-2" role="group" aria-label="Filter log">
        {(["all", "dispatch", "alerts", "ingest"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
            className={cn(
              "rounded px-2 py-1 text-xs capitalize text-fg-muted hover:bg-raised",
              filter === value && "bg-raised text-fg",
            )}
          >
            {value}
          </button>
        ))}
      </div>
      <ol className="max-h-[360px] flex-1 overflow-y-auto font-mono text-xs" aria-live="polite">
        {shown.length === 0 && <li className="px-3 py-4 text-fg-subtle">No events for this filter.</li>}
        {shown.map((event, index) => (
          <li
            key={`${event.at}-${event.kind}-${index}`}
            className="flex gap-2 border-b px-3 py-2 last:border-b-0"
          >
            <span className="mt-0.5">{ICONS[event.level]}</span>
            <time
              className="shrink-0 tabular-nums text-fg-subtle"
              dateTime={event.at}
              title={fmtDateTime(event.at)}
            >
              {event.phase === "ingest" ? "ingest" : fmtDayClock(event.at)}
            </time>
            <span className={cn("min-w-0 break-words", event.level === "critical" && "text-overload")}>
              {event.message}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
