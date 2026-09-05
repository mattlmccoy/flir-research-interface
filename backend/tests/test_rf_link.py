from flir_research_interface.rf_link import RfLinkSettings, load_settings, save_settings


def test_default_settings():
    s = RfLinkSettings()
    assert s.auto_start_on_rf_on is True
    assert s.stop_on_rf_off is False  # keep recording for cooldown by default


def test_settings_roundtrip(tmp_path):
    save_settings(tmp_path, RfLinkSettings(auto_start_on_rf_on=False, stop_on_rf_off=True))
    loaded = load_settings(tmp_path)
    assert loaded.auto_start_on_rf_on is False
    assert loaded.stop_on_rf_off is True


def test_load_missing_returns_defaults(tmp_path):
    assert load_settings(tmp_path) == RfLinkSettings()
