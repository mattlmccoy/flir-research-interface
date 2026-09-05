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


from flir_research_interface.rf_link import plan_rf_action


def test_rf_on_when_idle_and_autostart_starts_and_marks():
    a = plan_rf_action(state="on", is_recording=False, link_owns=False,
                       settings=RfLinkSettings(auto_start_on_rf_on=True))
    assert a.mark is True and a.start is True and a.stop is False


def test_rf_on_when_already_recording_only_marks():
    a = plan_rf_action(state="on", is_recording=True, link_owns=False, settings=RfLinkSettings())
    assert a.mark is True and a.start is False and a.stop is False


def test_rf_off_keep_recording_by_default_marks_only():
    a = plan_rf_action(state="off", is_recording=True, link_owns=True,
                       settings=RfLinkSettings(stop_on_rf_off=False))
    assert a.mark is True and a.stop is False


def test_rf_off_stops_only_when_configured_and_link_owned():
    owned = plan_rf_action(state="off", is_recording=True, link_owns=True,
                           settings=RfLinkSettings(stop_on_rf_off=True))
    assert owned.stop is True
    operator = plan_rf_action(state="off", is_recording=True, link_owns=False,
                              settings=RfLinkSettings(stop_on_rf_off=True))
    assert operator.stop is False  # never stop an operator-owned run
