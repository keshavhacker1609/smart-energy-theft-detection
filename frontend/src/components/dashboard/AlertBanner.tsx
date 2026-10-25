import { AnimatePresence, motion } from "framer-motion";
import { TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { fmtClock } from "@/lib/format";
import type { ForecastRun } from "@/lib/types";

const MAX_LISTED = 6;

function dismissedKey(runId: string): string {
  return `gridcast-alert-dismissed-${runId}`;
}

function isDismissed(runId: string): boolean {
  try {
    return sessionStorage.getItem(dismissedKey(runId)) === "1";
  } catch {
    return false;
  }
}

export function AlertBanner({ run }: { run: ForecastRun }) {
  const [dismissed, setDismissed] = useState(() => isDismissed(run.id));
  const { overload_at: times, peak_kw: peak } = run.summary;
  const visible = times.length > 0 && !dismissed;

  const dismiss = () => {
    setDismissed(true);
    try {
      sessionStorage.setItem(dismissedKey(run.id), "1");
    } catch {
      // Dismissal then lasts until the page reloads.
    }
  };

  const listed = times.slice(0, MAX_LISTED).map(fmtClock).join(", ");
  const more = times.length > MAX_LISTED ? ` and ${times.length - MAX_LISTED} more` : "";

  return (
    <AnimatePresence initial={false}>
      {visible && (
        <motion.div
          role="alert"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <div className="flex items-start gap-3 rounded-lg border border-overload/50 bg-overload-soft px-4 py-3">
            <TriangleAlert className="mt-0.5 size-5 shrink-0 text-overload" aria-hidden />
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-semibold text-overload">Critical overload forecast</p>
              <p className="text-fg">
                <span className="num">{listed}</span>
                {more} — peak <span className="num font-semibold">{peak.toFixed(1)} kW</span>. Demand at or
                above the overload threshold; storage dispatch and load shedding should be prepared.
              </p>
            </div>
            <Button variant="ghost" size="icon" onClick={dismiss} aria-label="Dismiss overload alert">
              <X />
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
