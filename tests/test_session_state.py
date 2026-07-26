"""Unit tests for utils/session_state.py, grounded in real captured payloads where possible."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

import pytest

from utils.session_state import SessionState, parse_gap_seconds, deep_merge, parse_lap_time_to_seconds

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


def test_deep_merge_indexes_a_list_before_merging_a_dict_diff_into_it() -> None:
    """Regression test: F1 sends TimingAppData.Stints as a plain array in a full-state
    snapshot but as an index-keyed dict in incremental diffs - confirmed live, merging a
    dict diff straight into the existing array (without normalizing it first) hit the
    "not both dicts" branch and replaced the whole array, silently discarding Compound
    (and everything else only ever sent once, in the array form)."""
    base = {
        "Stints": [
            {"Compound": "MEDIUM", "New": "true", "TotalLaps": 6},
        ]
    }
    deep_merge(base, {"Stints": {"0": {"TotalLaps": 7}}})
    assert base == {
        "Stints": {
            "0": {"Compound": "MEDIUM", "New": "true", "TotalLaps": 7},
        }
    }


def test_deep_merge_leaves_a_list_alone_when_the_update_is_also_a_list() -> None:
    """The list->dict normalization must only trigger when the incoming update is itself
    a dict (the incremental-diff form) - a list replacing a list is a normal, correct
    full replace and must not be reinterpreted as an indexed collection."""
    base = {"Sectors": [1, 2, 3]}
    deep_merge(base, {"Sectors": [4, 5]})
    assert base == {"Sectors": [4, 5]}


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


def test_lap_completion_still_produced_when_no_telemetry_was_buffered() -> None:
    """CarData.z can be absent for an entire live session (confirmed against a real one) -
    lap number/duration/gap-to-ahead must still reach Postgres even with no telemetry to
    attach; only the aggregates come back all-None."""
    state = SessionState()
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]
    state.apply("TimingData", msgs[0])
    diff = state.apply("TimingData", msgs[1])  # no telemetry buffered this time

    assert len(diff.completed_laps) == 1
    completed = diff.completed_laps[0]
    assert completed.lap_number == 1
    assert completed.lap_duration_seconds == pytest.approx(87.150)
    assert completed.aggregates.avg_speed_kmh is None
    assert completed.aggregates.max_speed_kmh is None


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


def test_team_radio_qualifying_part_is_none_outside_qualifying() -> None:
    """A race (or practice) session never sets SessionState.qualifying_part - a radio
    capture during one must carry qualifying_part=None, not a stale/guessed segment."""
    state = SessionState()
    state.apply("SessionInfo", {"Type": "Race"})
    state.apply("TimingData", {"Lines": {"1": {"NumberOfLaps": 5}}})

    diff = state.apply("TeamRadio", FIXTURES["team_radio_list_form"])
    assert diff.new_radio_captures[0].qualifying_part is None


def test_team_radio_enriches_qualifying_part_during_qualifying() -> None:
    """A capture during Q2 must carry qualifying_part="Q2" (see _apply_session_data's
    QualifyingPart transition and _apply_session_info's Q1 default)."""
    state = SessionState()
    state.apply("SessionInfo", {"Type": "Qualifying"})  # defaults qualifying_part to "Q1"
    state.apply("SessionData", {"Series": {"0": {"QualifyingPart": 2}}})  # Q1 -> Q2

    diff = state.apply("TeamRadio", FIXTURES["team_radio_list_form"])
    assert diff.new_radio_captures[0].qualifying_part == "Q2"


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
    assert snap["tyre_strategy_predictions"] == {}


def test_set_driver_roster_is_reflected_in_snapshot() -> None:
    state = SessionState()
    state.set_driver_roster({1: {"full_name": "Max Verstappen", "name_acronym": "VER"}})
    assert state.snapshot()["driver_roster"] == {1: {"full_name": "Max Verstappen", "name_acronym": "VER"}}


def test_unknown_topic_does_not_raise() -> None:
    state = SessionState()
    diff = state.apply("Heartbeat", {"Utc": "2025-01-01T00:00:00Z"})
    assert diff.event_name == "Heartbeat"
    assert diff.changed_driver_numbers == []


# ---- event_time (threaded through every diff, regardless of topic) ----

def test_apply_attaches_event_time_to_the_returned_diff() -> None:
    state = SessionState()
    event_time = datetime(2026, 7, 25, 16, 31, 47)
    diff = state.apply("WeatherData", {"AirTemp": "25.1"}, event_time=event_time)
    assert diff.event_time == event_time


def test_apply_event_time_defaults_to_none() -> None:
    state = SessionState()
    diff = state.apply("WeatherData", {"AirTemp": "25.1"})
    assert diff.event_time is None


def test_apply_attaches_event_time_even_for_an_unknown_topic() -> None:
    state = SessionState()
    event_time = datetime(2026, 7, 25, 16, 31, 47)
    diff = state.apply("Heartbeat", {"Utc": "..."}, event_time=event_time)
    assert diff.event_time == event_time


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


# ---- TopThree: full-snapshot "Lines" arrives as a list, not a dict ----

def test_top_three_handles_a_list_shaped_lines_from_the_initial_snapshot() -> None:
    """Regression test: TopThree's full-state snapshot (Subscribe RPC's initial-state
    result) sends "Lines" as a plain 3-entry array, not the index-keyed dict incremental
    diffs use - confirmed live, this crashed with AttributeError: 'list' object has no
    attribute 'items' the first time an initial snapshot ever reached this handler."""
    state = SessionState()
    diff = state.apply(
        "TopThree",
        {"Lines": [{"RacingNumber": "81", "Tla": "PIA"}, {"RacingNumber": "1", "Tla": "NOR"}]},
    )
    assert diff.changed_driver_numbers == [1, 2]
    assert state.top_three[1]["Tla"] == "PIA"
    assert state.top_three[2]["Tla"] == "NOR"


def test_top_three_still_handles_the_normal_dict_shaped_lines_diff() -> None:
    state = SessionState()
    state.apply("TopThree", {"Lines": [{"RacingNumber": "81", "Tla": "PIA"}]})
    diff = state.apply("TopThree", {"Lines": {"1": {"DiffToLeader": "+0.166"}}})
    assert diff.changed_driver_numbers == [1]
    assert state.top_three[1] == {"RacingNumber": "81", "Tla": "PIA", "DiffToLeader": "+0.166"}


# ---- Battle Radar: parse_gap_seconds ----

@pytest.mark.parametrize(
    "value,expected",
    [("+0.880", 0.880), ("+1.234", 1.234), ("0.500", 0.5), ("1L", None), (None, None), ("", None)],
)
def test_parse_gap_seconds(value, expected) -> None:
    result = parse_gap_seconds(value)
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
    """Live sampling (see _record_live_gap_sample) records a sample from the very first
    IntervalToPositionAhead-bearing message, not just once a lap actually completes - so
    exactly one message means exactly one sample, never enough for a trend on its own."""
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")
    assert 44 not in state.battle_radar


def test_battle_radar_fires_battle_tier_after_two_closing_laps() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")  # first sample: lap 1 = 2.5s
    _advance_with_gap(state, 44, 2, "2", "+1.800")  # lap 2 = 1.8s
    _advance_with_gap(state, 44, 3, "2", "+1.100")  # lap 3 = 1.1s, decreasing -> gaining

    alert = state.battle_radar[44]
    assert alert["alert_level"] == "battle"
    assert alert["gap_seconds"] == pytest.approx(1.1)
    assert alert["lap_history"] == [
        {"lap_number": 1, "gap_seconds": pytest.approx(2.5)},
        {"lap_number": 2, "gap_seconds": pytest.approx(1.8)},
        {"lap_number": 3, "gap_seconds": pytest.approx(1.1)},
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
    # 7 messages -> 7 live gap samples (every message with a gap value samples now, not
    # just lap-boundary ones) - the oldest 2 are evicted, keeping laps 3-7.
    assert len(state.battle_radar[44]["lap_history"]) == 5
    assert state.battle_radar[44]["lap_history"][0]["lap_number"] == 3  # oldest sample evicted


def test_battle_radar_touched_reported_on_diff_and_reflected_in_snapshot() -> None:
    state = SessionState()
    _advance_with_gap(state, 44, 1, "2", "+2.500")
    diff = state.apply(
        "TimingData", {"Lines": {"44": {"NumberOfLaps": 2, "Position": "2", "IntervalToPositionAhead": {"Value": "+1.800"}}}}
    )
    assert diff.battle_radar_touched == [44]
    assert state.snapshot()["battle_radar"] == state.battle_radar


# ---- Battle Radar: live (not lap-boundary) sampling + real-event-time throttling ----
#
# Confirmed live during an actual race: sampling only at lap boundaries (once every
# ~80-90s) meant a closing trend was only ever confirmed a full lap after it started - by
# the time it was confirmed, the overtake attempt it should have warned about had often
# already happened. Battle Radar now samples on every live IntervalToPositionAhead update,
# throttled by real *event* time (not wall-clock, so a fast-forward replay throttles
# correctly by race time elapsed, not by how fast it's processed) rather than gated on a
# lap actually completing.

def _gap_update(driver_number: int, position: str, gap_value: str) -> Dict:
    return {"Lines": {str(driver_number): {"Position": position, "IntervalToPositionAhead": {"Value": gap_value}}}}


def test_live_gap_sample_fires_mid_lap_without_a_lap_boundary() -> None:
    """The core fix: two closing readings on the SAME lap (no NumberOfLaps change at all
    between them) must be able to fire an alert - this could never happen under the old
    lap-boundary-only sampling."""
    state = SessionState()
    t0 = datetime(2026, 7, 26, 15, 0, 0)
    state.apply("TimingData", _gap_update(44, "2", "+2.500"), event_time=t0)
    state.apply("TimingData", _gap_update(44, "2", "+1.100"), event_time=t0 + timedelta(seconds=10))

    alert = state.battle_radar[44]
    assert alert["alert_level"] == "battle"
    assert alert["gap_seconds"] == pytest.approx(1.1)


def test_live_gap_sample_is_throttled_within_the_interval() -> None:
    """A second reading arriving before _LIVE_GAP_SAMPLE_INTERVAL_SECONDS has elapsed (in
    event time) must not be recorded - this is what keeps the trend check from flickering
    on ordinary measurement noise between consecutive ticks."""
    state = SessionState()
    t0 = datetime(2026, 7, 26, 15, 0, 0)
    state.apply("TimingData", _gap_update(44, "2", "+2.500"), event_time=t0)
    diff = state.apply("TimingData", _gap_update(44, "2", "+1.100"), event_time=t0 + timedelta(seconds=1))

    assert diff.battle_radar_touched == []
    assert 44 not in state.battle_radar  # only one sample was ever actually recorded


def test_live_gap_sample_records_again_once_the_interval_has_elapsed() -> None:
    state = SessionState()
    t0 = datetime(2026, 7, 26, 15, 0, 0)
    state.apply("TimingData", _gap_update(44, "2", "+2.500"), event_time=t0)
    state.apply("TimingData", _gap_update(44, "2", "+1.100"), event_time=t0 + timedelta(seconds=1))  # throttled
    diff = state.apply(
        "TimingData", _gap_update(44, "2", "+0.900"), event_time=t0 + timedelta(seconds=5)
    )  # interval elapsed since t0's sample

    assert diff.battle_radar_touched == [44]
    assert state.battle_radar[44]["gap_seconds"] == pytest.approx(0.9)


def test_live_gap_sample_tags_current_in_progress_lap_not_the_completed_one() -> None:
    """Unlike _record_gap_sample's completed-lap invariant, a live sample is tagged with
    whatever lap the driver is currently on - several samples can legitimately share one
    lap_number if multiple ticks land within it before the next boundary."""
    state = SessionState()
    t0 = datetime(2026, 7, 26, 15, 0, 0)
    state.apply("TimingData", {"Lines": {"44": {"NumberOfLaps": 5}}}, event_time=t0)  # first sighting
    diff = state.apply("TimingData", _gap_update(44, "2", "+1.500"), event_time=t0 + timedelta(seconds=1))

    assert diff.battle_radar_touched == [44]
    history = state._gap_history[44]
    assert history[-1] == (5, pytest.approx(1.5))


def test_completed_lap_gap_to_ahead_is_independent_of_live_sampling_throttle() -> None:
    """CompletedLap.gap_to_ahead_seconds (persisted per completed lap) must reflect the
    lap-boundary message's own value even when the live Battle Radar sampler is currently
    throttled - the two are decoupled (_current_gap_to_ahead is a pure read, not gated by
    _LIVE_GAP_SAMPLE_INTERVAL_SECONDS)."""
    state = SessionState()
    t0 = datetime(2026, 7, 26, 15, 0, 0)
    state.apply("TimingData", {"Lines": {"44": {"NumberOfLaps": 1}}}, event_time=t0)
    state.apply("TimingData", _gap_update(44, "2", "+2.000"), event_time=t0 + timedelta(milliseconds=100))

    # Lap boundary arrives well within the throttle window of the sample just above.
    diff = state.apply(
        "TimingData",
        {"Lines": {"44": {"NumberOfLaps": 2, "IntervalToPositionAhead": {"Value": "+0.750"}}}},
        event_time=t0 + timedelta(milliseconds=200),
    )

    completed = next(lap for lap in diff.completed_laps if lap.driver_number == 44)
    assert completed.gap_to_ahead_seconds == pytest.approx(0.750)


# ---- qualifying_part (SessionData.Series -> QualifyingPart) ----
# Confirmed live against a real Q1->Q2 transition: F1 sends this exact shape
# ({"Series": {"2": {"Utc": ..., "QualifyingPart": 2}}}) at the instant the new segment
# begins, simultaneously with every driver's TimingData resetting.

def test_qualifying_part_starts_unset() -> None:
    state = SessionState()
    assert state.qualifying_part is None


def test_qualifying_part_defaults_to_q1_once_session_info_reveals_qualifying_type() -> None:
    """F1 never sends an explicit QualifyingPart:1 announcement (confirmed live - only the
    Q1->Q2 and Q2->Q3 transitions get one), so this default is the only way qualifying_part
    is ever "Q1" rather than staying None for the whole first segment."""
    state = SessionState()
    state.apply("SessionInfo", {"Key": 9850, "Type": "Qualifying"})
    assert state.qualifying_part == "Q1"


def test_qualifying_part_stays_none_for_a_non_qualifying_session() -> None:
    state = SessionState()
    state.apply("SessionInfo", {"Key": 9850, "Type": "Race"})
    assert state.qualifying_part is None


def test_session_info_default_does_not_clobber_an_already_known_part() -> None:
    state = SessionState()
    state.apply("SessionInfo", {"Key": 9850, "Type": "Qualifying"})
    state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})

    state.apply("SessionInfo", {"ArchiveStatus": {"Status": "Complete"}})  # another SessionInfo update

    assert state.qualifying_part == "Q2"  # must not reset back to "Q1"


def test_qualifying_part_set_from_session_data_series() -> None:
    state = SessionState()
    state.apply("SessionData", {"Series": {"1": {"Utc": "2026-07-25T14:00:00Z", "QualifyingPart": 1}}})
    assert state.qualifying_part == "Q1"

    state.apply("SessionData", {"Series": {"2": {"Utc": "2026-07-25T14:24:00Z", "QualifyingPart": 2}}})
    assert state.qualifying_part == "Q2"


def test_qualifying_part_ignores_session_data_without_a_series() -> None:
    state = SessionState()
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    state.apply("SessionData", {"StatusSeries": {"5": {"SessionStatus": "Finished"}}})
    assert state.qualifying_part == "Q1"


def test_qualifying_part_reflected_in_snapshot() -> None:
    state = SessionState()
    state.apply("SessionData", {"Series": {"3": {"QualifyingPart": 3}}})
    assert state.snapshot()["qualifying_part"] == "Q3"


# ---- eliminated_drivers (bottom QUALIFYING_ELIMINATION_COUNT at each part transition) ----

def _set_positions(state: SessionState, positions: Dict[int, str]) -> None:
    state.apply("TimingData", {"Lines": {str(d): {"Position": p} for d, p in positions.items()}})


def test_no_eliminations_on_the_very_first_qualifying_part() -> None:
    state = SessionState()
    _set_positions(state, {d: str(d) for d in range(1, 23)})  # 22 drivers, positions 1-22
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    assert state.eliminated_drivers == set()


def test_bottom_six_eliminated_on_transition_to_q2() -> None:
    state = SessionState()
    _set_positions(state, {d: str(d) for d in range(1, 23)})  # driver N sits in position N
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})

    state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})

    assert state.eliminated_drivers == {17, 18, 19, 20, 21, 22}
    assert state.qualifying_part == "Q2"


def test_bottom_six_eliminated_on_transition_to_q3_excludes_already_eliminated() -> None:
    state = SessionState()
    _set_positions(state, {d: str(d) for d in range(1, 23)})
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})  # eliminates 17-22

    # Q2 reshuffles among the 16 remaining - simulate a new bottom-6 among positions 11-16.
    _set_positions(state, {d: str(d) for d in range(1, 17)})
    state.apply("SessionData", {"Series": {"3": {"QualifyingPart": 3}}})

    assert state.eliminated_drivers == {11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22}


def test_eliminated_drivers_skip_entries_without_a_known_position() -> None:
    state = SessionState()
    _set_positions(state, {d: str(d) for d in range(1, 17)})  # only 16 of 22 have a Position
    state.apply("TimingData", {"Lines": {"17": {}, "18": {}}})  # seen, but no Position yet
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})

    state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})

    assert state.eliminated_drivers == {11, 12, 13, 14, 15, 16}


def test_eliminated_drivers_reflected_in_snapshot() -> None:
    state = SessionState()
    _set_positions(state, {d: str(d) for d in range(1, 23)})
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})

    assert state.snapshot()["eliminated_drivers"] == [17, 18, 19, 20, 21, 22]


# ---- qualifying_gaps (computed from BestLapTime, never trusted from F1's Stats field) ----

def _set_best_lap(state: SessionState, driver_number: int, value: str) -> None:
    state.apply("TimingData", {"Lines": {str(driver_number): {"BestLapTime": {"Value": value}}}})


def test_leader_has_zero_gap() -> None:
    state = SessionState()
    _set_best_lap(state, 1, "1:20.000")
    assert state.qualifying_gaps[1] == 0.0


def test_gap_is_the_difference_to_the_leader() -> None:
    state = SessionState()
    _set_best_lap(state, 1, "1:20.000")
    _set_best_lap(state, 44, "1:20.500")
    assert state.qualifying_gaps[1] == 0.0
    assert state.qualifying_gaps[44] == pytest.approx(0.5)


def test_gap_recomputed_for_every_driver_when_the_leader_changes() -> None:
    """The core bug this fixes: F1's own Stats field never updates the outgoing leader's
    gap back to a nonzero value, or the new leader's down to zero - confirmed live (a real
    P1 driver kept showing a stale nonzero gap). Our own computation must get this right."""
    state = SessionState()
    _set_best_lap(state, 1, "1:20.000")  # 1 leads
    _set_best_lap(state, 44, "1:19.500")  # 44 takes over as leader

    assert state.qualifying_gaps[44] == 0.0
    assert state.qualifying_gaps[1] == pytest.approx(0.5)


def test_driver_with_no_valid_best_lap_has_no_gap_entry() -> None:
    state = SessionState()
    _set_best_lap(state, 1, "1:20.000")
    state.apply("TimingData", {"Lines": {"44": {"Position": "2"}}})  # seen, no BestLapTime yet

    assert 44 not in state.qualifying_gaps


def test_deleted_best_lap_removes_driver_from_gaps_and_recomputes_leader() -> None:
    state = SessionState()
    _set_best_lap(state, 1, "1:19.000")  # leader
    _set_best_lap(state, 44, "1:20.000")
    assert state.qualifying_gaps[44] == pytest.approx(1.0)

    _set_best_lap(state, 1, "")  # driver 1's only lap deleted - F1 clears BestLapTime.Value

    assert 1 not in state.qualifying_gaps
    assert state.qualifying_gaps[44] == 0.0  # 44 is now the only valid time, so the new leader


def test_qualifying_gaps_reset_on_a_new_qualifying_part() -> None:
    state = SessionState()
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    _set_best_lap(state, 1, "1:20.000")
    assert state.qualifying_gaps  # non-empty

    state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})

    assert state.qualifying_gaps == {}


def test_qualifying_gaps_reflected_in_snapshot() -> None:
    state = SessionState()
    _set_best_lap(state, 1, "1:20.000")
    assert state.snapshot()["qualifying_gaps"] == {1: 0.0}


# ---- qualifying_part_results (persisted snapshot at the end of each segment) ----

def test_no_results_snapshot_on_the_very_first_qualifying_part() -> None:
    state = SessionState()
    _set_positions(state, {1: "1", 2: "2"})
    diff = state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    assert diff.qualifying_part_results == []


def test_results_snapshot_produced_on_transition_tagged_with_the_ending_part() -> None:
    state = SessionState()
    _set_positions(state, {d: str(d) for d in range(1, 23)})
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    _set_best_lap(state, 1, "1:20.000")

    diff = state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})

    assert len(diff.qualifying_part_results) == 22
    entry_for_1 = next(r for r in diff.qualifying_part_results if r.driver_number == 1)
    assert entry_for_1.qualifying_part == "Q1"  # ending part, not "Q2"
    assert entry_for_1.position == 1
    assert entry_for_1.best_lap_seconds == pytest.approx(80.0)
    assert entry_for_1.gap_to_leader_seconds == pytest.approx(0.0)
    assert entry_for_1.eliminated is False

    entry_for_22 = next(r for r in diff.qualifying_part_results if r.driver_number == 22)
    assert entry_for_22.eliminated is True  # bottom 6 of positions 1-22


def test_results_snapshot_entry_has_none_fields_for_a_driver_with_no_valid_lap() -> None:
    state = SessionState()
    _set_positions(state, {d: str(d) for d in range(1, 23)})
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})

    diff = state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})

    entry = next(r for r in diff.qualifying_part_results if r.driver_number == 1)
    assert entry.best_lap_seconds is None
    assert entry.gap_to_leader_seconds is None


def test_finalised_session_status_snapshots_the_current_part_once() -> None:
    state = SessionState()
    _set_positions(state, {1: "1", 2: "2"})
    state.apply("SessionData", {"Series": {"3": {"QualifyingPart": 3}}})
    _set_best_lap(state, 1, "1:15.000")

    diff = state.apply("SessionStatus", {"Status": "Finalised"})

    assert len(diff.qualifying_part_results) == 2
    assert diff.qualifying_part_results[0].qualifying_part == "Q3"

    # A second "Finalised" message must not re-trigger the snapshot.
    diff2 = state.apply("SessionStatus", {"Status": "Finalised"})
    assert diff2.qualifying_part_results == []


def test_finalised_session_status_is_a_no_op_outside_qualifying() -> None:
    state = SessionState()
    diff = state.apply("SessionStatus", {"Status": "Finalised"})
    assert diff.qualifying_part_results == []


def test_non_finalised_session_status_does_not_snapshot() -> None:
    state = SessionState()
    state.apply("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})
    diff = state.apply("SessionStatus", {"Status": "Started"})
    assert diff.qualifying_part_results == []


# ---- SessionStatus "Started": formation lap telemetry flush (race/sprint only) ----
#
# F1 never assigns TimingData.NumberOfLaps to the formation lap - confirmed against real
# captured race data, it's simply absent until a driver completes the first real racing
# lap, at which point it appears already at 1 (never 0). Without an explicit flush at the
# green flag, all the grid/formation-lap CarData.z/Position.z samples silently carry over
# into lap 1's buffer and pollute its aggregates with formation-lap pace.

def test_session_status_started_during_race_flushes_buffered_telemetry_as_lap_zero() -> None:
    state = SessionState()
    state.apply("SessionInfo", {"Type": "Race"})
    state.apply("CarData.z", FIXTURES["car_data_raw_payload"])
    some_driver = next(iter(state._telemetry_buffers))
    assert len(state._buffer_for(some_driver).speed) > 0

    diff = state.apply("SessionStatus", {"Status": "Started"})

    formation_lap = next(lap for lap in diff.completed_laps if lap.driver_number == some_driver)
    assert formation_lap.lap_number == 0
    assert formation_lap.lap_duration_seconds is None
    assert formation_lap.gap_to_ahead_seconds is None
    assert formation_lap.qualifying_part is None
    # Buffer must be reset afterward, or lap 1 would inherit these same formation-lap samples.
    assert state._buffer_for(some_driver).speed == []


def test_session_status_started_is_a_no_op_outside_race_and_sprint_sessions() -> None:
    """Regression test: qualifying genuinely sends SessionStatus "Started" too (once per
    segment, confirmed against a real captured quali session) - this must never flush a
    driver's in-progress out-lap telemetry as a bogus "formation lap"."""
    state = SessionState()
    state.apply("SessionInfo", {"Type": "Qualifying"})
    state.apply("CarData.z", FIXTURES["car_data_raw_payload"])
    some_driver = next(iter(state._telemetry_buffers))

    diff = state.apply("SessionStatus", {"Status": "Started"})

    assert diff.completed_laps == []
    assert len(state._buffer_for(some_driver).speed) > 0  # untouched


def test_session_status_started_produces_no_record_for_a_driver_with_nothing_buffered() -> None:
    state = SessionState()
    state.apply("SessionInfo", {"Type": "Race"})
    diff = state.apply("SessionStatus", {"Status": "Started"})
    assert diff.completed_laps == []


def test_session_status_started_only_flushes_once() -> None:
    state = SessionState()
    state.apply("SessionInfo", {"Type": "Race"})
    state.apply("CarData.z", FIXTURES["car_data_raw_payload"])

    diff = state.apply("SessionStatus", {"Status": "Started"})
    assert len(diff.completed_laps) > 0

    state.apply("CarData.z", FIXTURES["car_data_raw_payload"])
    diff2 = state.apply("SessionStatus", {"Status": "Started"})
    assert diff2.completed_laps == []


def test_formation_lap_flush_does_not_pollute_the_next_real_completed_lap() -> None:
    """End-to-end: formation-lap samples must never reach lap 1's persisted telemetry."""
    state = SessionState()
    state.apply("SessionInfo", {"Type": "Race"})

    # Formation lap: three samples buffered before the green flag.
    for _ in range(3):
        state._buffer_for(81).add_car_sample(
            utc=datetime(2026, 7, 26, 14, 0, 0), rpm=10000, speed_kmh=60, gear=2,
            throttle_pct=30, brake_pct=0, drs=0,
        )
    state.apply("SessionStatus", {"Status": "Started"})
    assert state._buffer_for(81).speed == []  # flushed clean

    # Lap 1: two samples buffered after the green flag, at real racing pace.
    for _ in range(2):
        state._buffer_for(81).add_car_sample(
            utc=datetime(2026, 7, 26, 14, 1, 0), rpm=11500, speed_kmh=310, gear=8,
            throttle_pct=100, brake_pct=0, drs=1,
        )
    state.apply("TimingData", {"Lines": {"81": {"NumberOfLaps": 1}}})  # first sighting, no-op
    diff = state.apply("TimingData", {"Lines": {"81": {"NumberOfLaps": 2}}})  # lap 1 completes

    lap_one = next(lap for lap in diff.completed_laps if lap.driver_number == 81)
    assert lap_one.lap_number == 1
    assert lap_one.telemetry.speed == [310, 310]  # only the post-green-flag samples


def test_completed_lap_tagged_with_current_qualifying_part() -> None:
    state = SessionState()
    state.apply("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]

    state.apply("TimingData", msgs[0])
    state._buffer_for(81).add_car_sample(
        utc=datetime(2025, 11, 30, 16, 0, 0),
        rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )
    diff = state.apply("TimingData", msgs[1])

    assert diff.completed_laps[0].qualifying_part == "Q2"


def test_completed_lap_qualifying_part_is_none_outside_qualifying() -> None:
    state = SessionState()
    msgs = FIXTURES["timing_data_lap_progression_driver_81"]

    state.apply("TimingData", msgs[0])
    state._buffer_for(81).add_car_sample(
        utc=datetime(2025, 11, 30, 16, 0, 0),
        rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )
    diff = state.apply("TimingData", msgs[1])

    assert diff.completed_laps[0].qualifying_part is None


# ---- deleted-lap parsing from RaceControlMessages ----
# Both message formats confirmed live in a real qualifying session.

def test_race_control_parses_deletion_with_explicit_time() -> None:
    state = SessionState()
    diff = state.apply(
        "RaceControlMessages",
        {"Messages": {"1": {"Message": "CAR 55 (SAI) TIME 1:23.576 DELETED - TRACK LIMITS AT TURN 4 LAP 3 16:02:17"}}},
    )
    assert len(diff.deleted_laps) == 1
    assert diff.deleted_laps[0].driver_number == 55
    assert diff.deleted_laps[0].lap_number == 3


def test_race_control_parses_deletion_without_explicit_time() -> None:
    state = SessionState()
    diff = state.apply(
        "RaceControlMessages",
        {"Messages": {"1": {"Message": "CAR 10 (GAS) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 4 16:08:19 (PIT)"}}},
    )
    assert len(diff.deleted_laps) == 1
    assert diff.deleted_laps[0].driver_number == 10
    assert diff.deleted_laps[0].lap_number == 4


def test_race_control_ignores_messages_without_a_deletion() -> None:
    state = SessionState()
    diff = state.apply(
        "RaceControlMessages", {"Messages": {"1": {"Message": "GREEN LIGHT - PIT EXIT OPEN"}}}
    )
    assert diff.deleted_laps == []


def test_race_control_handles_multiple_deletions_in_one_message() -> None:
    state = SessionState()
    diff = state.apply(
        "RaceControlMessages",
        {
            "Messages": {
                "1": {"Message": "CAR 55 (SAI) TIME 1:23.576 DELETED - TRACK LIMITS AT TURN 4 LAP 3 16:02:17"},
                "2": {"Message": "CAR 16 (LEC) TIME 1:18.878 DELETED - TRACK LIMITS AT TURN 3 LAP 3 16:04:20"},
            }
        },
    )
    assert {(d.driver_number, d.lap_number) for d in diff.deleted_laps} == {(55, 3), (16, 3)}
