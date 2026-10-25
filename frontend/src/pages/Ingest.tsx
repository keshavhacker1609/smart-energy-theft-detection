import { ArrowRight, ClipboardList, FileSpreadsheet, Keyboard } from "lucide-react";
import { Link } from "react-router";
import { CsvUpload } from "@/components/ingest/CsvUpload";
import { ManualForm } from "@/components/ingest/ManualForm";
import { IssueTable, QualityReport } from "@/components/ingest/QualityReport";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useConfig } from "@/hooks/queries";
import { useActiveRun } from "@/hooks/useActiveRun";
import { fmtDateTime } from "@/lib/format";

export default function IngestPage() {
  const config = useConfig();
  const { run, lastError } = useActiveRun();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Ingest telemetry</h1>
        <p className="text-sm text-fg-muted">
          Upload a CSV or enter hourly readings. Data is validated, cleaned and forecast through the QuickML
          endpoint; every repair is listed in the data quality report.
        </p>
      </div>
      <Card>
        <CardContent>
          {config.data ? (
            <Tabs defaultValue="upload" className="space-y-4">
              <TabsList>
                <TabsTrigger value="upload">
                  <FileSpreadsheet aria-hidden /> Upload CSV
                </TabsTrigger>
                <TabsTrigger value="manual">
                  <Keyboard aria-hidden /> Manual entry
                </TabsTrigger>
              </TabsList>
              <TabsContent value="upload">
                <CsvUpload maxBytes={config.data.max_upload_bytes} />
              </TabsContent>
              <TabsContent value="manual">
                <ManualForm maxRows={config.data.max_manual_rows} />
              </TabsContent>
            </Tabs>
          ) : (
            <Skeleton className="h-48 w-full" />
          )}
        </CardContent>
      </Card>

      {lastError && (
        <Card className="border-overload/40">
          <CardHeader>
            <CardTitle className="text-overload">Input rejected</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm">{lastError.message}</p>
            {lastError.body.issues && lastError.body.issues.length > 0 && (
              <IssueTable issues={lastError.body.issues} />
            )}
          </CardContent>
        </Card>
      )}

      {run && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardList className="size-4" aria-hidden /> Data quality report
            </CardTitle>
            <div className="flex items-center gap-3">
              <span className="hidden text-xs text-fg-muted sm:inline">
                {run.filename ?? "manual entry"} · {fmtDateTime(run.created_at)}
              </span>
              <Button asChild size="sm" variant="primary">
                <Link to="/">
                  View dashboard <ArrowRight />
                </Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <QualityReport report={run.quality} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
