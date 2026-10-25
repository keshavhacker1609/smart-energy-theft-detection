# Deployment on Zoho Catalyst

| Module | Service | Source |
|---|---|---|
| Model | QuickML endpoint | `ml/quickml_train.csv` |
| API, cleaning, controller, battery simulation | AppSail (Python) | `backend/` |
| Raw uploads, full run documents | Stratus | bucket `telemetry-uploads` |
| Run index, per-hour signals | Data Store | tables `ForecastRuns`, `ForecastHours` |
| Dashboard | Slate | `frontend/` |

## 1. QuickML

1. Upload `ml/quickml_train.csv` as a dataset. Every column is numeric; `target_demand_kw` is the target.
2. Build a regression pipeline using Linear Regression, with no extra encoding or scaling of the
   `h_XX` one-hot columns. Train it.
3. Record the leaderboard RMSE in `ml/README.md`, then publish the endpoint.
4. From the endpoint page, copy the URL and the endpoint key into `.env`.
5. Create a Zoho API Console self-client and generate a refresh token with the QuickML scope.
   Put its client id, secret and refresh token into `.env`.
6. Run `python ml/holdout_check.py` and `python test_eval.py`.

The client sends one row per request as `{"data": {...features}}`, with the headers
`Authorization: Zoho-oauthtoken <token>` and `X-QUICKML-ENDPOINT-KEY`. This is the same request
`zcatalyst_sdk`'s `QuickML.predict` builds. Rows are sent concurrently (`QUICKML_MAX_WORKERS`).

## 2. Data Store

Create two tables. The column names must match exactly. `ROWID` and `CREATEDTIME` are added
automatically.

`ForecastRuns`: `run_id` (varchar 64, unique), `source` (varchar), `filename` (varchar),
`row_count` (int), `window_start` (varchar), `peak_kw` (double), `overload_hours` (int),
`transitions` (int), `current_mode` (varchar), `rows_rejected` (int), `rows_imputed` (int),
`document_key` (varchar), `upload_key` (varchar), `summary_json` (text).

`ForecastHours`: `run_id` (varchar 64), `hour_ts` (varchar), `ambient_temp_c` (double),
`humidity_pct` (double), `solar_irradiance_wm2` (double), `predicted_kw` (double),
`grid_mode` (varchar), `overload` (boolean), `soc_pct` (double), `reasons` (text).

## 3. Stratus

Create the bucket `telemetry-uploads`. The API writes `uploads/<run_id>.csv` (the raw file) and
`runs/<run_id>.json` (the full run, used to reload it from History).

## 4. AppSail

- Build path: `backend/`. Stack: Python 3.11 or newer. Start command: `python3 -m app`.
  It listens on `X_ZOHO_CATALYST_LISTEN_PORT`.
- Environment variables: everything in `.env.example`, with `STORAGE_BACKEND=catalyst` and
  `CORS_ORIGINS` set to the Slate URL.
- `GET /api/health` reports QuickML and storage separately. If storage is down, forecasts are still
  returned, flagged `persisted: false`.

## 5. Slate

Build the frontend with `VITE_API_BASE_URL` set to the AppSail URL, then deploy `frontend/dist`.
