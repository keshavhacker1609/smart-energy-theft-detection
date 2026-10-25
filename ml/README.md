# Demand model

Everything here is reproducible from `ml/data/train_telemetry.csv`:

```bash
pip install -r requirements-dev.txt
python ml/train.py     # knee search, model comparison, writes feature spec + QuickML exports
python ml/eda.py       # figures -> docs/figures/
```

## Findings

- 4,000 hourly rows, 2014-12-31 23:00 to 2015-06-16 14:00, no gaps, no missing values.
  `sample_test_input.csv` continues the series from 2015-06-16 15:00 to 2015-07-28 06:00
  (mean 29.2 °C, versus 17.0 °C in training), so the model must extrapolate into hotter weather.
- Demand is set mainly by hour of day, as a step profile: about 92 kW at 00–05, a ramp at 06–07,
  160–185 kW through the day, 205–220 kW at 18–22, and a drop at 23 (`docs/figures/hourly_profile.png`).
- Cooling load is the only material weather effect. Above the knee demand rises by 8.6 kW per °C,
  and the slope is the same at every hour of the day: fitting per hour gives 8.0–10.6 kW/°C
  (`docs/figures/cooling_knee.png`). Humidity, irradiance and weekday/weekend add nothing once
  hour and cooling degrees are in the model.
- The residual standard deviation within each hour, after removing cooling load, is about 8 kW.
  The selected model's error is at that noise floor.

## Features (`backend/app/features.py`)

| Feature | Definition |
|---|---|
| `h_01` … `h_23` | one-hot hour of day; hour 00 is the reference level |
| `cdd` | `max(0, temp − 24.0)` |
| `hdd` | `max(0, 2.5 − temp)` |
| `humidity_pct`, `solar_irradiance_wm2` | raw |

The knees are learned by grid search, scored by TimeSeriesSplit CV on the first 80% of the data.
They are stored in `backend/app/feature_spec.json`, which both training and inference read.
Raw temperature is deliberately left out. Next to `cdd`/`hdd` it is collinear: the knees drift
around 22–25 °C with no change in score, and the cooling knee stops being identifiable. Without
it, the top five knee candidates all land on 24.0 °C. The heating knee is weakly identified and
does not matter for the forecast horizon: every row of the test input is above 19 °C, so `hdd = 0`.

## Model selection

TimeSeriesSplit, 5 expanding folds, over all 4,000 rows. Holdout means: fit on the first 80%, then
score the last 20% in time order.

| Model | CV fold RMSE (kW) | CV mean | Holdout |
|---|---|---:|---:|
| Linear, raw weather only (baseline) | 38.5 / 44.9 / 42.9 / 49.4 / 54.2 | 45.99 | 54.19 |
| LightGBM, raw weather + hour + weekday | 9.2 / 9.1 / 16.1 / 17.6 / 17.6 | 13.93 | 14.51 |
| LightGBM, engineered features | 10.2 / 11.7 / 18.8 / 17.9 / 22.3 | 16.19 | 24.97 |
| **Linear, hour + CDD/HDD (selected)** | 8.7 / 8.5 / 9.6 / 8.5 / 8.3 | **8.71** | **8.30** |
| Ridge, hour + CDD/HDD | 8.7 / 8.5 / 9.6 / 8.5 / 8.3 | 8.71 | 8.30 |
| ElasticNet, hour + CDD/HDD | 8.7 / 8.5 / 9.7 / 8.5 / 8.3 | 8.74 | 8.28 |
| Linear + GBM on residuals | 8.9 / 8.6 / 9.8 / 8.7 / 8.5 | 8.89 | 8.40 |

Optional terms, each added to the selected linear model (CV mean): `cdd × daytime` 8.89,
`cdd²` 10.02, `is_weekend` 8.72. None improves on 8.71, so none is kept.

Tree models get worse fold by fold as the folds move into warmer months. They cannot predict
beyond the hottest temperature they have seen, so they plateau. The linear model keeps the same
error in every fold. Selection rule (in `ml/train.py`): lowest CV mean among models that can
extrapolate in temperature, with ties within 1% going to the simplest. Ridge and OLS tie, so OLS wins.

## QuickML

1. Upload `ml/quickml_train.csv` (engineered features plus `target_demand_kw`) as a QuickML dataset.
   To get a strictly out-of-sample holdout figure, train once on `ml/quickml_train_dev.csv` first.
2. Build a regression pipeline with target `target_demand_kw` and the Linear Regression algorithm.
   Do not let QuickML add its own scaling or encoding of the one-hot columns.
3. Publish the endpoint. Copy its URL, auth and headers into `.env` (see `.env.example`).
4. `python ml/holdout_check.py` scores the live endpoint on the last 20% of training data.

QuickML leaderboard result: _not yet recorded_.

## Local reference endpoint

`ml/local_endpoint.py` serves the same OLS model over HTTP, with the same request and response
format as the client. Development and CI use it to exercise `predict.py` without Catalyst
credentials. It is never deployed:

```bash
python ml/local_endpoint.py --port 8765 &
QUICKML_ENDPOINT_URL=http://127.0.0.1:8765/predict python test_eval.py
```
