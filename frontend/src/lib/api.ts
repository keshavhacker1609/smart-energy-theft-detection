import type {
  ApiErrorBody,
  AppConfig,
  BatteryParams,
  ForecastRun,
  Health,
  ModelCard,
  RunListItem,
  SimulateResponse,
  TelemetryRow,
} from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(body.detail);
    this.status = status;
    this.body = body;
  }

  get retryable(): boolean {
    return this.body.retryable ?? (this.status === 0 || this.status >= 500);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...init, signal: controller.signal });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(0, {
      detail: timedOut
        ? "The forecast service did not respond in time. Check your connection and retry."
        : "Cannot reach the forecast service. Check your connection and retry.",
      retryable: true,
    });
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    let body: ApiErrorBody = { detail: `Request failed with HTTP ${response.status}` };
    try {
      const parsed = (await response.json()) as Partial<ApiErrorBody>;
      if (typeof parsed.detail === "string") body = { ...parsed, detail: parsed.detail };
    } catch {
      // Non-JSON error bodies keep the generic message.
    }
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  health: () => request<Health>("/api/health"),
  config: () => request<AppConfig>("/api/config"),
  modelCard: () => request<ModelCard>("/api/model"),
  runs: (limit = 50) => request<RunListItem[]>(`/api/runs?limit=${limit}`),
  run: (id: string) => request<ForecastRun>(`/api/runs/${encodeURIComponent(id)}`),
  upload: (file: File, battery?: BatteryParams) => {
    const form = new FormData();
    form.append("file", file);
    if (battery) form.append("battery", JSON.stringify(battery));
    return request<ForecastRun>("/api/forecast/upload", { method: "POST", body: form });
  },
  manual: (rows: TelemetryRow[], battery?: BatteryParams) =>
    postJson<ForecastRun>("/api/forecast/manual", { rows, battery }),
  simulate: (rows: TelemetryRow[], temperatureOffsetC: number, battery: BatteryParams) =>
    postJson<SimulateResponse>("/api/simulate", {
      rows,
      temperature_offset_c: temperatureOffsetC,
      battery,
    }),
};
