import pytest
from pydantic import ValidationError

from app.config import Settings


def test_environment_overrides_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_THRESHOLD_KW", "150")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example"]')
    settings = Settings()
    assert settings.rules.storage_threshold_kw == 150
    assert settings.cors_origins == ["https://app.example"]


def test_defaults_match_specification() -> None:
    rules = Settings().rules
    assert (rules.storage_threshold_kw, rules.overload_threshold_kw) == (160, 200)
    assert (rules.peak_start_hour, rules.peak_end_hour) == (18, 22)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"storage_threshold_kw": 210}, "overload threshold"),
        ({"peak_start_hour": 22, "peak_end_hour": 18}, "wrap past midnight"),
        ({"battery_round_trip_efficiency": 0}, "greater than 0"),
    ],
)
def test_inconsistent_settings_are_rejected(overrides: dict[str, float], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(overrides)
