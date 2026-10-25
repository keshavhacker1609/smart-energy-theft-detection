import { Database, Loader2, Upload } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { useActiveRun } from "@/hooks/useActiveRun";

export function EmptyState({ title, description }: { title: string; description: string }) {
  const { forecast, isForecasting } = useActiveRun();
  return (
    <div className="flex flex-col items-center gap-4 rounded-lg border border-dashed bg-surface px-6 py-16 text-center">
      <div className="grid size-12 place-items-center rounded-full bg-raised">
        <Database className="size-5 text-fg-muted" aria-hidden />
      </div>
      <div className="max-w-md space-y-1">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-fg-muted">{description}</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        <Button variant="primary" onClick={() => forecast({ kind: "sample" })} disabled={isForecasting}>
          {isForecasting ? <Loader2 className="animate-spin" /> : <Database />}
          {isForecasting ? "Forecasting sample data…" : "Try sample data"}
        </Button>
        <Button asChild>
          <Link to="/ingest">
            <Upload />
            Upload telemetry
          </Link>
        </Button>
      </div>
      <p className="text-xs text-fg-subtle">
        Sample data is the starter kit's sample_test_input.csv, run through the full pipeline.
      </p>
    </div>
  );
}
