import { FileUp, Loader2, Play, X } from "lucide-react";
import Papa from "papaparse";
import { type DragEvent, useId, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useActiveRun } from "@/hooks/useActiveRun";
import { type Canonical, type CellState, checkCell, mapHeaders, REQUIRED } from "@/lib/preview";
import { cn } from "@/lib/utils";

const PREVIEW_ROWS = 50;

interface Parsed {
  file: File;
  headers: string[];
  rows: Record<string, string>[];
  totalRows: number;
  parseErrors: number;
}

const CELL_STYLE: Record<CellState, string> = {
  ok: "",
  missing: "bg-warning-soft",
  invalid: "bg-overload-soft text-overload",
  range: "bg-warning-soft text-warning",
};

const CELL_TITLE: Record<CellState, string | undefined> = {
  ok: undefined,
  missing: "Missing: the API will interpolate short gaps",
  invalid: "Not parseable: will be treated as missing",
  range: "Outside physical range: clipped or treated as missing",
};

export function CsvUpload({ maxBytes }: { maxBytes: number }) {
  const inputId = useId();
  const { forecast, isForecasting } = useActiveRun();
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const load = (file: File) => {
    setError(null);
    if (file.size > maxBytes) {
      setParsed(null);
      setError(
        `${file.name} is ${(file.size / 1e6).toFixed(1)} MB; the limit is ${(maxBytes / 1e6).toFixed(1)} MB.`,
      );
      return;
    }
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: "greedy",
      complete: (result) => {
        setParsed({
          file,
          headers: result.meta.fields ?? [],
          rows: result.data.slice(0, PREVIEW_ROWS),
          totalRows: result.data.length,
          parseErrors: result.errors.length,
        });
      },
      error: (err) => setError(`Could not read ${file.name}: ${err.message}`),
    });
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) load(file);
  };

  const check = useMemo(() => {
    if (!parsed) return null;
    const { mapping, missing } = mapHeaders(parsed.headers);
    const counts: Record<CellState, number> = { ok: 0, missing: 0, invalid: 0, range: 0 };
    for (const row of parsed.rows) {
      for (const column of REQUIRED) {
        const header = mapping[column];
        if (header) counts[checkCell(column, row[header])] += 1;
      }
    }
    return { mapping, missing, counts };
  }, [parsed]);

  return (
    <div className="space-y-4">
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors focus-within:border-accent hover:border-border-strong",
          dragging && "border-accent bg-grid-soft",
        )}
      >
        <FileUp className="size-6 text-fg-muted" aria-hidden />
        <span className="text-sm font-medium">Drop a telemetry CSV here, or click to browse</span>
        <span className="text-xs text-fg-subtle">
          Columns: timestamp, ambient_temp_c, humidity_pct, solar_irradiance_wm2 (common variants accepted) ·
          max {(maxBytes / 1e6).toFixed(0)} MB
        </span>
        <input
          id={inputId}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) load(file);
            event.target.value = "";
          }}
        />
      </label>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-overload/40 bg-overload-soft px-3 py-2 text-sm text-overload"
        >
          {error}
        </p>
      )}

      {parsed && check && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{parsed.file.name}</span>
            <Badge>{parsed.totalRows} rows</Badge>
            {check.missing.length === 0 ? (
              <Badge tone="storage">All required columns found</Badge>
            ) : (
              <Badge tone="overload">Missing: {check.missing.join(", ")}</Badge>
            )}
            {check.counts.missing > 0 && <Badge tone="warning">{check.counts.missing} empty cells</Badge>}
            {check.counts.invalid > 0 && <Badge tone="overload">{check.counts.invalid} unparseable</Badge>}
            {check.counts.range > 0 && <Badge tone="warning">{check.counts.range} out of range</Badge>}
            {parsed.parseErrors > 0 && <Badge tone="warning">{parsed.parseErrors} malformed lines</Badge>}
            <div className="ml-auto flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => setParsed(null)}>
                <X /> Clear
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={check.missing.length > 0 || isForecasting}
                onClick={() => forecast({ kind: "upload", file: parsed.file, stay: true })}
              >
                {isForecasting ? <Loader2 className="animate-spin" /> : <Play />}
                {isForecasting ? "Forecasting…" : "Run forecast"}
              </Button>
            </div>
          </div>
          <div className="max-h-80 overflow-auto rounded-md border">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-raised">
                <tr>
                  <th className="px-2 py-1.5 font-medium text-fg-muted">#</th>
                  {parsed.headers.map((header) => (
                    <th key={header} className="whitespace-nowrap px-2 py-1.5 font-medium text-fg-muted">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="num">
                {parsed.rows.map((row, index) => (
                  <tr key={index} className="border-t">
                    <td className="px-2 py-1 text-fg-subtle">{index + 1}</td>
                    {parsed.headers.map((header) => {
                      const column = (Object.entries(check.mapping).find(([, h]) => h === header)?.[0] ??
                        null) as Canonical | null;
                      const state = column ? checkCell(column, row[header]) : "ok";
                      return (
                        <td
                          key={header}
                          title={CELL_TITLE[state]}
                          className={cn("whitespace-nowrap px-2 py-1", CELL_STYLE[state])}
                        >
                          {row[header] || "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {parsed.totalRows > PREVIEW_ROWS && (
            <p className="text-xs text-fg-subtle">
              Showing the first {PREVIEW_ROWS} of {parsed.totalRows} rows. All rows are forecast; the
              dashboard shows the first 24 hours from the earliest timestamp.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
