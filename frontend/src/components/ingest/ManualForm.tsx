import { zodResolver } from "@hookform/resolvers/zod";
import { addHours, format, parse } from "date-fns";
import { CalendarClock, Loader2, Play, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { useActiveRun } from "@/hooks/useActiveRun";
import type { TelemetryRow } from "@/lib/types";

const LOCAL_FORMAT = "yyyy-MM-dd'T'HH:mm";

function optionalNumber(min: number, max: number, unit: string) {
  return z.string().refine((value) => {
    if (value.trim() === "") return true;
    const number = Number(value);
    return Number.isFinite(number) && number >= min && number <= max;
  }, `${min} to ${max} ${unit}`);
}

const rowSchema = z.object({
  timestamp: z
    .string()
    .min(1, "Required")
    .refine((value) => !Number.isNaN(Date.parse(value)), "Invalid date/time"),
  ambient_temp_c: optionalNumber(-30, 55, "°C"),
  humidity_pct: optionalNumber(0, 100, "%"),
  solar_irradiance_wm2: optionalNumber(0, 1500, "W/m²"),
});

type FormRow = z.infer<typeof rowSchema>;
type FormValues = { rows: FormRow[] };

const emptyRow = (timestamp = ""): FormRow => ({
  timestamp,
  ambient_temp_c: "",
  humidity_pct: "",
  solar_irradiance_wm2: "",
});

const toNumber = (value: string): number | null => (value.trim() === "" ? null : Number(value));

function toTelemetry(row: FormRow): TelemetryRow {
  return {
    timestamp: `${row.timestamp.replace("T", " ")}:00`,
    ambient_temp_c: toNumber(row.ambient_temp_c),
    humidity_pct: toNumber(row.humidity_pct),
    solar_irradiance_wm2: toNumber(row.solar_irradiance_wm2),
  };
}

const FIELDS: { name: keyof Omit<FormRow, "timestamp">; label: string; step: string }[] = [
  { name: "ambient_temp_c", label: "Temp °C", step: "0.1" },
  { name: "humidity_pct", label: "Humidity %", step: "0.1" },
  { name: "solar_irradiance_wm2", label: "Irradiance W/m²", step: "1" },
];

export function ManualForm({ maxRows }: { maxRows: number }) {
  const { forecast, isForecasting } = useActiveRun();
  const schema = useMemo(
    () => z.object({ rows: z.array(rowSchema).min(1).max(maxRows, `At most ${maxRows} rows`) }),
    [maxRows],
  );
  const [start, setStart] = useState(() => format(new Date().setMinutes(0, 0, 0), LOCAL_FORMAT));
  const [count, setCount] = useState(maxRows);
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { rows: [emptyRow()] } });
  const { fields, append, remove, replace } = useFieldArray({ control: form.control, name: "rows" });
  const errors = form.formState.errors.rows;

  const generate = () => {
    const base = parse(start, LOCAL_FORMAT, new Date());
    if (Number.isNaN(base.getTime())) return;
    const existing = form.getValues("rows");
    const n = Math.max(1, Math.min(maxRows, count));
    replace(
      Array.from({ length: n }, (_, i) => ({
        ...(existing[i] ?? emptyRow()),
        timestamp: format(addHours(base, i), LOCAL_FORMAT),
      })),
    );
  };

  const submit = form.handleSubmit((values) =>
    forecast({ kind: "manual", rows: values.rows.map(toTelemetry), stay: true }),
  );

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <fieldset className="flex flex-wrap items-end gap-3 rounded-md border bg-raised/50 p-3">
        <legend className="sr-only">Generate hourly timestamps</legend>
        <div className="space-y-1">
          <Label htmlFor="gen-start">Start</Label>
          <Input
            id="gen-start"
            type="datetime-local"
            step={3600}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="w-24 space-y-1">
          <Label htmlFor="gen-count">Hours</Label>
          <Input
            id="gen-count"
            type="number"
            min={1}
            max={maxRows}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
          />
        </div>
        <Button onClick={generate}>
          <CalendarClock /> Generate hourly timestamps
        </Button>
        <p className="w-full text-xs text-fg-subtle">
          Weather values already entered are kept row by row. Empty values are interpolated by the API when
          the gap is short, and reported in the data quality report.
        </p>
      </fieldset>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-left text-xs text-fg-muted">
              <th className="w-8 pb-2 font-medium">#</th>
              <th className="pb-2 font-medium">Timestamp</th>
              {FIELDS.map((f) => (
                <th key={f.name} className="pb-2 font-medium">
                  {f.label}
                </th>
              ))}
              <th className="w-10 pb-2" />
            </tr>
          </thead>
          <tbody>
            {fields.map((field, index) => {
              const rowErrors = errors?.[index];
              return (
                <tr key={field.id} className="align-top">
                  <td className="num py-1 pr-2 pt-3 text-xs text-fg-subtle">{index + 1}</td>
                  <td className="py-1 pr-2">
                    <Input
                      type="datetime-local"
                      step={3600}
                      aria-label={`Row ${index + 1} timestamp`}
                      aria-invalid={Boolean(rowErrors?.timestamp)}
                      {...form.register(`rows.${index}.timestamp`)}
                    />
                    {rowErrors?.timestamp && (
                      <p className="mt-1 text-xs text-overload">{rowErrors.timestamp.message}</p>
                    )}
                  </td>
                  {FIELDS.map((f) => (
                    <td key={f.name} className="py-1 pr-2">
                      <Input
                        type="number"
                        inputMode="decimal"
                        step={f.step}
                        className="num"
                        aria-label={`Row ${index + 1} ${f.label}`}
                        aria-invalid={Boolean(rowErrors?.[f.name])}
                        {...form.register(`rows.${index}.${f.name}`)}
                      />
                      {rowErrors?.[f.name] && (
                        <p className="mt-1 text-xs text-overload">{rowErrors[f.name]?.message}</p>
                      )}
                    </td>
                  ))}
                  <td className="py-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => remove(index)}
                      disabled={fields.length === 1}
                      aria-label={`Remove row ${index + 1}`}
                    >
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {errors?.root?.message && <p className="text-sm text-overload">{errors.root.message}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => append(emptyRow())} disabled={fields.length >= maxRows}>
          <Plus /> Add row
        </Button>
        <span className="text-xs text-fg-subtle">
          {fields.length} / {maxRows} rows
        </span>
        <Button type="submit" variant="primary" className="ml-auto" disabled={isForecasting}>
          {isForecasting ? <Loader2 className="animate-spin" /> : <Play />}
          {isForecasting ? "Forecasting…" : "Run forecast"}
        </Button>
      </div>
    </form>
  );
}
