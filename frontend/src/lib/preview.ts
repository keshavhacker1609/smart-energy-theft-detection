// Client-side preview checks so problems are visible before upload. The API's cleaning step is authoritative.

export type Canonical = "timestamp" | "ambient_temp_c" | "humidity_pct" | "solar_irradiance_wm2";

const ALIASES: Record<Canonical, string[]> = {
  timestamp: ["timestamp", "time", "datetime", "date_time", "ts", "hour_start"],
  ambient_temp_c: [
    "ambient_temp_c",
    "ambient_temp",
    "temp",
    "temp_c",
    "temperature",
    "temperature_c",
    "ambient_temperature",
  ],
  humidity_pct: ["humidity_pct", "humidity", "relative_humidity", "rh", "humidity_percent"],
  solar_irradiance_wm2: [
    "solar_irradiance_wm2",
    "solar_irradiance",
    "irradiance",
    "solar",
    "ghi",
    "irradiance_wm2",
    "solar_irradiance_w_m2",
    "irradiance_w_m2",
  ],
};

const RANGES: Partial<Record<Canonical, [number, number]>> = {
  ambient_temp_c: [-30, 55],
  humidity_pct: [0, 100],
  solar_irradiance_wm2: [0, 1500],
};

export const REQUIRED: Canonical[] = ["timestamp", "ambient_temp_c", "humidity_pct", "solar_irradiance_wm2"];

const normalise = (header: string) =>
  header
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");

export function mapHeaders(headers: string[]): {
  mapping: Partial<Record<Canonical, string>>;
  missing: Canonical[];
} {
  const mapping: Partial<Record<Canonical, string>> = {};
  for (const header of headers) {
    const key = normalise(header);
    const match = (Object.keys(ALIASES) as Canonical[]).find((c) => ALIASES[c].includes(key));
    if (match && !mapping[match]) mapping[match] = header;
  }
  return { mapping, missing: REQUIRED.filter((c) => !mapping[c]) };
}

export type CellState = "ok" | "missing" | "invalid" | "range";

export function checkCell(column: Canonical, raw: string | undefined): CellState {
  const value = (raw ?? "").trim();
  if (!value || ["nan", "null", "none", "na", "n/a"].includes(value.toLowerCase())) return "missing";
  if (column === "timestamp") return Number.isNaN(Date.parse(value.replace(" ", "T"))) ? "invalid" : "ok";
  const number = Number(value);
  if (!Number.isFinite(number)) return "invalid";
  const range = RANGES[column];
  return range && (number < range[0] || number > range[1]) ? "range" : "ok";
}
