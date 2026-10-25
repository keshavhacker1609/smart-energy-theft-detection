// Mirrors backend/app/schemas.py.

export type GridMode = "MAIN_GRID" | "RENEWABLE_STORAGE";
export type RunSource = "upload" | "manual";

export interface TelemetryRow {
  timestamp: string;
  ambient_temp_c: number | null;
  humidity_pct: number | null;
  solar_irradiance_wm2: number | null;
}

export interface BatteryParams {
  capacity_kwh: number;
  initial_soc_pct: number;
  reserve_soc_pct: number;
  max_charge_kw: number;
  max_discharge_kw: number;
  round_trip_efficiency: number;
  solar_reference_wm2: number;
}

export interface Issue {
  row: number | null;
  column: string | null;
  kind: string;
  detail: string;
  action: string;
}

export interface Gap {
  after: string;
  before: string;
  missing_hours: number;
}

export interface QualityReport {
  rows_received: number;
  rows_accepted: number;
  rows_imputed: number;
  rows_rejected: number;
  values_imputed: number;
  values_clipped: number;
  duplicates_removed: number;
  columns_renamed: Record<string, string>;
  gaps: Gap[];
  issues: Issue[];
  issues_truncated: number;
}

export interface Hour {
  timestamp: string;
  source_row: number;
  ambient_temp_c: number;
  humidity_pct: number;
  solar_irradiance_wm2: number;
  imputed: string[];
  predicted_kw: number;
  actual_kw: number | null;
  mode: GridMode;
  overload: boolean;
  reasons: string[];
  soc_pct: number;
  battery_discharge_kw: number;
  battery_charge_kw: number;
  grid_kw: number;
  reserve_low: boolean;
}

export interface Summary {
  window_start: string;
  window_end: string;
  window_hours: number;
  current_mode: GridMode;
  next_transition_at: string | null;
  next_transition_mode: GridMode | null;
  transitions: number;
  storage_hours: number;
  grid_hours: number;
  overload_hours: number;
  overload_at: string[];
  peak_kw: number;
  peak_at: string;
  grid_energy_avoided_kwh: number;
  reserve_low_hours: number;
  min_soc_pct: number;
  final_soc_pct: number;
  actual_rmse_kw: number | null;
  actual_rows: number;
}

export interface LogEvent {
  at: string;
  phase: "ingest" | "dispatch";
  level: "info" | "warning" | "critical";
  kind: string;
  message: string;
}

export interface ModelInfo {
  name: string;
  validation_rmse_kw: number;
}

export interface ForecastResult {
  hours: Hour[];
  summary: Summary;
  events: LogEvent[];
}

export interface ForecastRun extends ForecastResult {
  id: string;
  created_at: string;
  source: RunSource;
  filename: string | null;
  quality: QualityReport;
  battery: BatteryParams;
  model: ModelInfo;
  persisted: boolean;
  storage_warning: string | null;
}

export interface RunListItem {
  id: string;
  created_at: string;
  source: RunSource;
  filename: string | null;
  rows: number;
  window_start: string;
  current_mode: GridMode;
  peak_kw: number;
  overload_hours: number;
  transitions: number;
}

export interface ScenarioDelta {
  peak_kw: number;
  overload_hours: number;
  storage_hours: number;
  transitions: number;
  grid_energy_avoided_kwh: number;
  reserve_low_hours: number;
  min_soc_pct: number;
}

export interface SimulateResponse {
  baseline: ForecastResult;
  scenario: ForecastResult;
  delta: ScenarioDelta;
}

export interface ComponentHealth {
  ok: boolean;
  detail: string;
  latency_ms: number | null;
}

export interface Health {
  status: "ok" | "degraded";
  quickml: ComponentHealth;
  storage: ComponentHealth;
}

export interface AppConfig {
  storage_threshold_kw: number;
  overload_threshold_kw: number;
  peak_start_hour: number;
  peak_end_hour: number;
  horizon_hours: number;
  max_manual_rows: number;
  max_upload_bytes: number;
  temperature_offset_range_c: [number, number];
  battery: BatteryParams;
  model: ModelInfo;
}

export interface CandidateResult {
  name: string;
  cv_folds: number[];
  cv_mean: number;
  holdout_rmse: number;
  extrapolates: boolean;
}

export interface ModelCard {
  selected: string;
  algorithm: string;
  validation_rmse_kw: number;
  holdout_rmse_kw: number;
  selection_rule: string;
  why: string;
  training: { rows: number; start: string; end: string; n_splits: number; holdout_fraction: number };
  feature_spec: { cooling_base_c: number; heating_base_c: number };
  features: { name: string; description: string }[];
  feature_columns: string[];
  candidates: CandidateResult[];
  optional_terms_cv_mean: Record<string, number>;
  coefficients: Record<string, number>;
  hourly_profile: { hour: number; mean_kw: number; q25_kw: number; q75_kw: number }[];
  cooling_curve: { temp_c: number; mean_adjusted_kw: number; count: number }[];
  holdout_series: { timestamp: string; actual_kw: number; predicted_kw: number }[];
  holdout_scatter: [number, number][];
  residual_by_hour: { hour: number; median_kw: number; q25_kw: number; q75_kw: number }[];
  limitations: string[];
}

export interface ApiErrorBody {
  detail: string;
  issues?: Issue[];
  retryable?: boolean;
}
