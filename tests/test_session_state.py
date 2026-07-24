"""Unit tests for utils/session_state.py, grounded in real captured payloads where possible."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from utils.session_state import SessionState, deep_merge, parse_lap_time_to_seconds

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


def test_snapshot_returns_full_current_state() -> None:
    state = SessionState(session_key=9850)
    state.apply("WeatherData", {"AirTemp": "25.1"})
    snap = state.snapshot()
    assert snap["session_key"] == 9850
    assert snap["weather"] == {"AirTemp": "25.1"}


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
