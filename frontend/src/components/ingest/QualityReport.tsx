import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { fmtDateTime } from "@/lib/format";
import type { Issue, QualityReport as Report } from "@/lib/types";

const KIND_TONE: Record<string, "warning" | "overload" | "neutral" | "grid"> = {
  invalid_timestamp: "overload",
  gap_too_large: "overload",
  duplicate_timestamp: "warning",
  out_of_range: "warning",
  non_numeric: "warning",
  clipped: "neutral",
  imputed: "grid",
  unaligned_timestamp: "neutral",
};

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-md border bg-raised/40 px-3 py-2">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className={`num text-xl font-semibold ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

export function IssueTable({ issues, footer }: { issues: Issue[]; footer?: ReactNode }) {
  if (issues.length === 0) {
    return (
      <p className="flex items-center gap-2 text-sm text-storage">
        <CheckCircle2 className="size-4" aria-hidden /> No issues: every value was used as received.
      </p>
    );
  }
  return (
    <div className="max-h-80 overflow-auto rounded-md border">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-raised text-fg-muted">
          <tr>
            <th className="px-2 py-1.5 font-medium">Row</th>
            <th className="px-2 py-1.5 font-medium">Column</th>
            <th className="px-2 py-1.5 font-medium">Issue</th>
            <th className="px-2 py-1.5 font-medium">Detail</th>
            <th className="px-2 py-1.5 font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr key={index} className="border-t">
              <td className="num px-2 py-1">{issue.row ?? "—"}</td>
              <td className="px-2 py-1 font-mono">{issue.column ?? "—"}</td>
              <td className="px-2 py-1">
                <Badge tone={KIND_TONE[issue.kind] ?? "neutral"}>{issue.kind.replace(/_/g, " ")}</Badge>
              </td>
              <td className="px-2 py-1 text-fg-muted">{issue.detail}</td>
              <td className="px-2 py-1">{issue.action}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {footer}
    </div>
  );
}

export function QualityReport({ report }: { report: Report }) {
  const renamed = Object.entries(report.columns_renamed);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Received" value={report.rows_received} />
        <Stat label="Accepted" value={report.rows_accepted} tone="text-storage" />
        <Stat label="Imputed rows" value={report.rows_imputed} />
        <Stat
          label="Rejected"
          value={report.rows_rejected}
          tone={report.rows_rejected ? "text-overload" : ""}
        />
        <Stat label="Clipped values" value={report.values_clipped} />
        <Stat label="Duplicates removed" value={report.duplicates_removed} />
      </div>
      {renamed.length > 0 && (
        <p className="text-sm text-fg-muted">
          Columns mapped:{" "}
          {renamed.map(([from, to]) => (
            <span key={from} className="mr-2 font-mono text-xs">
              {from} → {to}
            </span>
          ))}
        </p>
      )}
      {report.gaps.length > 0 && (
        <div className="text-sm">
          <p className="font-medium">Gaps in the hourly sequence</p>
          <ul className="mt-1 space-y-0.5 text-fg-muted">
            {report.gaps.slice(0, 10).map((gap) => (
              <li key={gap.after} className="num text-xs">
                {gap.missing_hours} h missing between {fmtDateTime(gap.after)} and {fmtDateTime(gap.before)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <IssueTable
        issues={report.issues}
        footer={
          report.issues_truncated > 0 ? (
            <p className="border-t px-2 py-1.5 text-xs text-fg-subtle">
              {report.issues_truncated} further issues not listed.
            </p>
          ) : undefined
        }
      />
    </div>
  );
}
