# Central config — edit here, nothing else needs touching.

# --- Server ---
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000
DEBUG       = True

# --- Detection Thresholds ---
THEFT_THRESHOLD  = 1.30   # actual > expected * 1.30 → HIGH / Theft
MEDIUM_THRESHOLD = 1.10   # actual > expected * 1.10 → MEDIUM / Suspicious

# --- Meter Definitions ---
# Baseline kWh per meter — used as default expected value in Force Theft demo.
METERS = {
    "M1": 5.0,
    "M2": 8.0,
    "M3": 3.5,
}

# --- Log ---
LOG_MAX_ENTRIES = 200     # max readings kept in memory

# --- Frontend ---
CHART_MAX_POINTS = 20     # rolling window size on trend chart
CHART_METER_ID   = "M1"  # which meter gets the trend chart
