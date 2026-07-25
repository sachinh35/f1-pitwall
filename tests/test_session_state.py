"""Unit tests for utils/session_state.py, grounded in real captured payloads where possible."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from utils.session_state import SessionState, _parse_gap_seconds, deep_merge, parse_lap_time_to_seconds

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "real_stream_samples.json").read_text())


# ---- deep_merge ----

def test_deep_merge_overwrites_scalars() -> None:
    base = {"a": 1, "b": 2}
    deep_merge(base, {"b": 3, "c": 4})
    assert base == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_recurses_into_nested_dicts_without_clobbering_siblings() -> None:
    base = {"Sectors": {"1": {"Value": "25.1"}, "2": {"Value": "30.0"}}}
    deep_merge(base, {"Sectors": {"1": {"Segments": {"0": {"Status": 2048}}}}})
    assert base == {
        "Sectors": {
            "1": {"Value": "25.1", "Segments": {"0": {"Status": 2048}}},
            "2": {"Value": "30.0"},
        }
    }


def test_deep_merge_replaces_when_types_diverge() -> None:
    base = {"GapToLeader": {"stale": "shape"}}
    deep_merge(base, {"GapToLeader": "+0.200"})
    assert base == {"GapToLeader": "+0.200"}


# ---- parse_lap_time_to_seconds ----

@pytest.mark.parametrize(
    "value,expected",
    [
        ("1:27.150", 87.150),
        ("26.930", 26.930),
        (None, None),
        ("", None),
        ("not-a-time", None),
    ],
)
def test_parse_lap_time_to_seconds(value: str, expected: float) -> None:
    result = parse_lap_time_to_seconds(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# ---- TimingData merge + lap completion, against the real lap-progression fixture ----

def test_timing_data_merge_accumulates_driver_state() -> None:
    state = SessionState(session_key=9850)
    for msg in FIXTURES["timing_data_lap_progression_driver_81"][:2]:
        state.apply("TimingData", msg)

    assert 81 in state.drivers
    assert state.drivers[81]["NumberOfLaps"] == 2


def test_lap_completion_not_fired_on_first_sighting() -> None:
    state = SessionState()
    first_msg = FIXTURES["timing_data_lap_progression_driver_81"][0]
    diff = state.apply("TimingData", first_msg)
    assert diff.completed_laps == []


def test_lap_completion_fires_on_number_of_laps_increase_with_buffered_telemetry() -> None:
    state = SessionState()
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]

    state.apply("TimingData", msgs[0])  # NumberOfLaps=1 - first sighting, nothing to complete yet

    # Simulate telemetry arriving during lap 1, before it completes.
    state._buffer_for(81).add_car_sample(
        utc=datetime(2025, 11, 30, 16, 0, 0),
        rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )

    diff = state.apply("TimingData", msgs[1])  # NumberOfLaps=2 -> lap 1 completes
    assert len(diff.completed_laps) == 1
    completed = diff.completed_laps[0]
    assert completed.driver_number == 81
    assert completed.lap_number == 1
    assert completed.lap_duration_seconds == pytest.approx(87.150)
    assert completed.aggregates.max_speed_kmh == 300
    assert completed.aggregates.drs_active_pct == 100


def test_completed_lap_carries_gap_to_ahead_seconds() -> None:
    state = SessionState()
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]

    state.apply("TimingData", msgs[0])  # NumberOfLaps=1
    state._buffer_for(81).add_car_sample(
        utc=datetime(2025, 11, 30, 16, 0, 0),
        rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )
    # The message carrying NumberOfLaps=2 also carries the gap that applied to lap 1,
    # matching real feed behavior (see _advance_lap's docstring).
    msg_with_gap = {"Lines": {"81": {**msgs[1]["Lines"]["81"], "IntervalToPositionAhead": {"Value": "+0.850"}}}}
    diff = state.apply("TimingData", msg_with_gap)

    assert diff.completed_laps[0].gap_to_ahead_seconds == pytest.approx(0.850)


def test_completed_lap_gap_to_ahead_seconds_is_none_when_unparseable() -> None:
    state = SessionState()
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]

    state.apply("TimingData", msgs[0])
    state._buffer_for(81).add_car_sample(
        utc=datetime(2025, 11, 30, 16, 0, 0),
        rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )
    diff = state.apply("TimingData", msgs[1])  # no IntervalToPositionAhead at all

    assert diff.completed_laps[0].gap_to_ahead_seconds is None


def test_lap_completion_skipped_when_no_telemetry_was_buffered() -> None:
    state = SessionState()
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]
    state.apply("TimingData", msgs[0])
    diff = state.apply("TimingData", msgs[1])  # no telemetry buffered this time
    assert diff.completed_laps == []


def test_current_lap_for_tracks_latest_value() -> None:
    state = SessionState()
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]
    for msg in msgs[:3]:
        state.apply("TimingData", msg)
    assert state.current_lap_for(81) == 3
    assert state.current_lap_for(999) is None


# ---- TeamRadio: both observed shapes (list on the first capture, dict afterwards) ----

def test_team_radio_handles_list_form() -> None:
    state = SessionState()
    diff = state.apply("TeamRadio", FIXTURES["team_radio_list_form"])
    assert len(diff.new_radio_captures) == 1
    capture = diff.new_radio_captures[0]
    assert capture.driver_number == 1
    assert capture.path == "TeamRadio/MAXVER01_1_20251130_191032.mp3"


def test_team_radio_handles_dict_form() -> None:
    state = SessionState()
    diff = state.apply("TeamRadio", FIXTURES["team_radio_dict_form"])
    assert len(diff.new_radio_captures) == 1
    assert diff.new_radio_captures[0].driver_number == 27


def test_team_radio_deduplicates_by_path_across_calls() -> None:
    state = SessionState()
    state.apply("TeamRadio", FIXTURES["team_radio_list_form"])
    diff = state.apply("TeamRadio", FIXTURES["team_radio_list_form"])  # same clip again
    assert diff.new_radio_captures == []


def test_team_radio_enriches_lap_number_from_reducer_state() -> None:
    state = SessionState()
    state.apply("TimingData", {"Lines": {"1": {"NumberOfLaps": 1}}})
    state.apply("TimingData", {"Lines": {"1": {"NumberOfLaps": 5}}})

    diff = state.apply("TeamRadio", FIXTURES["team_radio_list_form"])
    assert diff.new_radio_captures[0].lap_number == 5


# ---- Other topics: replace-style, Lines-style, append-only ----

def test_weather_data_is_replace_style_per_key() -> None:
    state = SessionState()
    state.apply("WeatherData", {"AirTemp": "25.1", "TrackTemp": "30.8"})
    state.apply("WeatherData", {"AirTemp": "25.4"})
    assert state.weather == {"AirTemp": "25.4", "TrackTemp": "30.8"}


def test_driver_list_merge_ignores_kf_flag_key() -> None:
    state = SessionState()
    state.apply("DriverList", {"4": {"Line": 3}, "_kf": True})
    assert state.driver_list == {4: {"Line": 3}}


def test_race_control_messages_append_only() -> None:
    state = SessionState()
    state.apply("RaceControlMessages", {"Messages": {"1": {"Message": "Green flag"}}})
    state.apply("RaceControlMessages", {"Messages": {"2": {"Message": "Yellow flag"}}})
    assert state.race_control_messages == {
        "1": {"Message": "Green flag"},
        "2": {"Message": "Yellow flag"},
    }


def test_weather_data_diff_carries_full_merged_snapshot_for_persistence() -> None:
    state = SessionState()
    state.apply("WeatherData", {"AirTemp": "25.1", "TrackTemp": "30.8"})
    diff = state.apply("WeatherData", {"AirTemp": "25.4"})
    # The persisted snapshot is the full merged weather, not just this message's fields.
    assert diff.new_weather_snapshot == {"AirTemp": "25.4", "TrackTemp": "30.8"}


def test_race_control_diff_carries_new_entries_for_persistence() -> None:
    state = SessionState()
    diff = state.apply("RaceControlMessages", {"Messages": {"4": {"Lap": 1, "Category": "Drs", "Message": "DRS DISABLED"}}})
    assert diff.new_race_control_entries == [
        {"index": "4", "Lap": 1, "Category": "Drs", "Message": "DRS DISABLED"}
    ]


def test_race_control_diff_empty_when_no_messages_key() -> None:
    state = SessionState()
    diff = state.apply("RaceControlMessages", {})
    assert diff.new_race_control_entries == []


def test_race_control_handles_list_form_on_first_message() -> None:
    """F1 sends Messages as a bare list (no index) on the very first RaceControlMessages event of a
    session, and as a dict afterwards - confirmed directly in three captured logs."""
    state = SessionState()
    diff = state.apply(
        "RaceControlMessages",
        {"Messages": [{"Utc": "2025-11-29T17:59:32", "Category": "Other", "Message": "PIT LANE INCIDENT"}]},
    )
    assert diff.new_race_control_entries == [
        {"index": "0", "Utc": "2025-11-29T17:59:32", "Category": "Other", "Message": "PIT LANE INCIDENT"}
    ]
    assert state.race_control_messages == {
        "0": {"Utc": "2025-11-29T17:59:32", "Category": "Other", "Message": "PIT LANE INCIDENT"}
    }


def test_race_control_list_form_synthetic_index_sorts_before_real_dict_indices() -> None:
    """The frontend's race control feed does Number(index) and sorts descending (newest first) - the
    synthetic index for a list-form message must parse as a number lower than any real F1 index, so
    that oldest-first ordering (list-form message is always the session's very first) stays correct."""
    state = SessionState()
    state.apply("RaceControlMessages", {"Messages": [{"Message": "first ever message"}]})
    state.apply("RaceControlMessages", {"Messages": {"1": {"Message": "second message"}}})

    indices_newest_first = sorted((int(i) for i in state.race_control_messages), reverse=True)
    assert indices_newest_first == [1, 0]


def test_race_control_list_form_with_multiple_items_gets_distinct_indices() -> None:
    state = SessionState()
    diff = state.apply(
        "RaceControlMessages",
        {"Messages": [{"Message": "first"}, {"Message": "second"}]},
    )
    assert diff.new_race_control_entries == [
        {"index": "0", "Message": "first"},
        {"index": "-1", "Message": "second"},
    ]


def test_snapshot_returns_full_current_state() -> None:
    state = SessionState(session_key=9850)
    state.apply("WeatherData", {"AirTemp": "25.1"})
    snap = state.snapshot()
    assert snap["session_key"] == 9850
    assert snap["weather"] == {"AirTemp": "25.1"}
    assert snap["driver_roster"] == {}


def test_set_driver_roster_is_reflected_in_snapshot() -> None:
    state = SessionState()
    state.set_driver_roster({1: {"full_name": "Max Verstappen", "name_acronym": "VER"}})
    assert state.snapshot()["driver_roster"] == {1: {"full_name": "Max Verstappen", "name_acronym": "VER"}}


def test_unknown_topic_does_not_raise() -> None:
    state = SessionState()
    diff = state.apply("Heartbeat", {"Utc": "2025-01-01T00:00:00Z"})
    assert diff.event_name == "Heartbeat"
    assert diff.changed_driver_numbers == []


# ---- SessionInfo: session_key/meeting_key capture ----

def test_session_info_captures_session_and_meeting_key() -> None:
    state = SessionState()
    state.apply("SessionInfo", {"Meeting": {"Key": 1275, "Name": "Qatar Grand Prix"}, "Key": 9850, "Type": "Race"})
    assert state.session_key == 9850
    assert state.meeting_key == 1275
    assert state.session_info["Type"] == "Race"


def test_session_info_without_key_fields_does_not_clobber_existing_values() -> None:
    state = SessionState(session_key=9850)
    state.meeting_key = 1275
    state.apply("SessionInfo", {"SessionStatus": "Started"})
    assert state.session_key == 9850
    assert state.meeting_key == 1275


# ---- latest_telemetry_sample / latest_position_sample ----

def test_latest_telemetry_sample_none_when_no_data_buffered() -> None:
    state = SessionState()
    assert state.latest_telemetry_sample(81) is None


def test_latest_telemetry_sample_reflects_most_recent_car_data() -> None:
    state = SessionState()
    state.apply("CarData.z", FIXTURES["car_data_raw_payload"])
    some_driver = next(iter(state._telemetry_buffers))
    sample = state.latest_telemetry_sample(some_driver)
    assert sample is not None
    assert set(sample.keys()) == {"speed_kmh", "rpm", "gear", "throttle_pct", "brake_pct", "drs"}


def test_latest_position_sample_reflects_most_recent_position() -> None:
    state = SessionState()
    state.apply("Position.z", FIXTURES["position_raw_payload"])
    some_driver = next(iter(state._telemetry_buffers))
    sample = state.latest_position_sample(some_driver)
    assert sample is not None
    assert set(sample.keys()) == {"x", "y", "z", "status"}


# ---- CarData.z / Position.z end-to-end through the reducer, using real payloads ----

def test_car_data_topic_buffers_samples_for_every_driver_seen() -> None:
    state = SessionState()
    diff = state.apply("CarData.z", FIXTURES["car_data_raw_payload"])
    assert diff.event_name == "CarData.z"
    assert len(diff.changed_driver_numbers) > 0
    some_driver = diff.changed_driver_numbers[0]
    assert len(state._buffer_for(some_driver).speed) > 0


def test_position_topic_buffers_samples_for_every_driver_seen() -> None:
    state = SessionState()
    diff = state.apply("Position.z", FIXTURES["position_raw_payload"])
    assert diff.event_name == "Position.z"
    some_driver = diff.changed_driver_numbers[0]
    assert len(state._buffer_for(some_driver).x) > 0


# ---- Battle Radar: _parse_gap_seconds ----

@pytest.mark.parametrize(
    "value,expected",
    [("+0.880", 0.880), ("+1.234", 1.234), ("0.500", 0.5), ("1L", None), (None, None), ("", None)],
)
def test_parse_gap_seconds(value, expected) -> None:
    result = _parse_gap_seconds(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# ---- Battle Radar: trend detection + alert tiers ----

def _advance_with_gap(state: SessionState, driver_number: int, lap_number: int, position: str, gap_value) -> None:
    """Simulate one TimingData message that both announces `lap_number` (via NumberOfLaps)
    and carries the gap-to-car-ahead that applied to the lap just completed - matching the
    real feed's shape, where LastLapTime/IntervalToPositionAhead ride along on the same
    message that bumps NumberOfLaps (see _advance_lap's docstring)."""
    fields = {"NumberOfLaps": lap_number, "Position": position}
    if gap_value is not None:
        fields["IntervalToPositionAhead"] = {"Value": gap_value}
    state.apply("TimingData", {"Lines": {str(driver_number): fields}})


def test_battle_radar_no_alert_with_only_one_gap_sample() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")  # first sighting, no advance yet
    _advance_with_gap(state, 44, 2, "2", "+1.100")  # lap 1 completes, records exactly one sample
    assert 44 not in state.battle_radar


def test_battle_radar_fires_battle_tier_after_two_closing_laps() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")
    _advance_with_gap(state, 44, 2, "2", "+1.800")  # records lap 1 = 1.8s
    _advance_with_gap(state, 44, 3, "2", "+1.100")  # records lap 2 = 1.1s, decreasing -> gaining

    alert = state.battle_radar[44]
    assert alert["alert_level"] == "battle"
    assert alert["gap_seconds"] == pytest.approx(1.1)
    assert alert["lap_history"] == [
        {"lap_number": 1, "gap_seconds": pytest.approx(1.8)},
        {"lap_number": 2, "gap_seconds": pytest.approx(1.1)},
    ]


def test_battle_radar_fires_upcoming_tier_between_thresholds() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")
    _advance_with_gap(state, 44, 2, "2", "+1.900")
    _advance_with_gap(state, 44, 3, "2", "+1.600")  # decreasing, but 1.3 <= 1.6 < 2.0

    assert state.battle_radar[44]["alert_level"] == "upcoming"


def test_battle_radar_no_alert_when_gap_is_flat() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+1.000")
    _advance_with_gap(state, 44, 2, "2", "+1.000")
    _advance_with_gap(state, 44, 3, "2", "+1.000")
    assert 44 not in state.battle_radar


def test_battle_radar_no_alert_when_gap_is_widening() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+1.000")
    _advance_with_gap(state, 44, 2, "2", "+1.500")
    _advance_with_gap(state, 44, 3, "2", "+2.000")
    assert 44 not in state.battle_radar


def test_battle_radar_alert_clears_once_gap_starts_widening_again() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")
    _advance_with_gap(state, 44, 2, "2", "+1.800")
    _advance_with_gap(state, 44, 3, "2", "+1.100")
    assert 44 in state.battle_radar  # closing - alert active

    _advance_with_gap(state, 44, 4, "2", "+1.900")  # widened again
    assert 44 not in state.battle_radar


def test_battle_radar_no_alert_for_leader_with_no_interval_field() -> None:
    state = SessionState()
    _advance_with_gap(state, 1, 1, "1", None)
    _advance_with_gap(state, 1, 2, "1", None)
    assert 1 not in state.battle_radar


def test_battle_radar_no_alert_for_lapped_car_interval() -> None:
    state = SessionState()
    _advance_with_gap(state, 20, 1, "18", "1L")
    _advance_with_gap(state, 20, 2, "18", "1L")
    assert 20 not in state.battle_radar


def test_battle_radar_resolves_ahead_driver_number_from_position() -> None:
    state = SessionState()
    state.apply("TimingData", {"Lines": {"1": {"Position": "1"}, "44": {"Position": "2"}}})
    _advance_with_gap(state, 44, 1, "2", "+2.500")
    _advance_with_gap(state, 44, 2, "2", "+1.800")
    _advance_with_gap(state, 44, 3, "2", "+1.100")

    assert state.battle_radar[44]["ahead_driver_number"] == 1


def test_battle_radar_lap_history_capped_at_five_samples() -> None:
    state = SessionState()
    gaps = ["+3.000", "+2.800", "+2.600", "+2.400", "+2.200", "+2.000", "+1.800"]
    for lap_number, gap in enumerate(gaps, start=1):
        _advance_with_gap(state, 44, lap_number, "2", gap)
    # 7 laps announced -> 6 gap samples recorded (first message only initializes NumberOfLaps).
    assert len(state.battle_radar[44]["lap_history"]) == 5
    assert state.battle_radar[44]["lap_history"][0]["lap_number"] == 2  # oldest sample evicted


def test_battle_radar_touched_reported_on_diff_and_reflected_in_snapshot() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")
    diff = state.apply(
        "TimingData", {"Lines": {"44": {"NumberOfLaps": 2, "Position": "2", "IntervalToPositionAhead": {"Value": "+1.800"}}}}
    )
    assert diff.battle_radar_touched == [44]
    assert state.snapshot()["battle_radar"] == state.battle_radar
