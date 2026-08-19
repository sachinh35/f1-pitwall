"""Unit tests for db/lap_comparison.py."""
import pytest

from db.lap_comparison import (
    LapTrace,
    build_lap_trace,
    compute_acceleration,
    compute_cumulative_distance,
    compute_delta_trace,
    detect_corners,
)


# ---- compute_cumulative_distance ----

def test_cumulative_distance_empty_input() -> None:
    assert compute_cumulative_distance([], []) == []


def test_cumulative_distance_straight_line() -> None:
    # Moving 3-4-5 triangle steps: each step is exactly distance 5.
    x = [0, 3, 6]
    y = [0, 4, 8]
    result = compute_cumulative_distance(x, y)
    assert result == pytest.approx([0.0, 5.0, 10.0])


def test_cumulative_distance_stationary_point_contributes_zero() -> None:
    x = [0, 0, 10]
    y = [0, 0, 0]
    result = compute_cumulative_distance(x, y)
    assert result == pytest.approx([0.0, 0.0, 10.0])


# ---- compute_acceleration ----

def test_acceleration_empty_input() -> None:
    assert compute_acceleration([], []) == []


def test_acceleration_constant_speed_is_zero() -> None:
    time_ms = [0, 250, 500, 750]
    speed = [200, 200, 200, 200]
    result = compute_acceleration(time_ms, speed)
    assert result == pytest.approx([0.0, 0.0, 0.0, 0.0])


def test_acceleration_known_speed_change() -> None:
    # 0 -> 36 km/h (= 10 m/s) over exactly 1 second -> 10 m/s^2.
    time_ms = [0, 1000]
    speed = [0, 36]
    result = compute_acceleration(time_ms, speed)
    assert result[1] == pytest.approx(10.0)


def test_acceleration_negative_for_braking() -> None:
    time_ms = [0, 1000]
    speed = [100, 64]  # -36 km/h = -10 m/s over 1s
    result = compute_acceleration(time_ms, speed)
    assert result[1] == pytest.approx(-10.0)


def test_acceleration_handles_zero_dt_without_crashing() -> None:
    time_ms = [0, 0, 100]
    speed = [50, 60, 70]
    result = compute_acceleration(time_ms, speed)
    assert len(result) == 3
    assert result[1] == result[0]  # zero-dt sample just repeats the previous value


# ---- build_lap_trace ----

def test_build_lap_trace_empty_inputs_return_empty_trace() -> None:
    trace = build_lap_trace([], [], [], [], [], [], [])
    assert trace.distance_m == []
    assert trace.speed_kmh == []


def test_build_lap_trace_interpolates_telemetry_onto_position_axis() -> None:
    # Position samples every 500ms; telemetry samples every 250ms (different
    # rate/axis - exactly the real-world mismatch this function exists to fix).
    position_dt_ms = [0, 500, 1000]
    x = [0, 100, 200]
    y = [0, 0, 0]
    telemetry_dt_ms = [0, 250, 500, 750, 1000]
    speed_kmh = [100, 150, 200, 250, 300]
    throttle_pct = [50, 60, 70, 80, 90]
    brake_pct = [0, 0, 0, 0, 0]

    trace = build_lap_trace(position_dt_ms, x, y, telemetry_dt_ms, speed_kmh, throttle_pct, brake_pct)

    assert trace.distance_m == pytest.approx([0.0, 100.0, 200.0])
    # At t=0 -> 100, t=500 -> 200 (exact telemetry samples), t=1000 -> 300 (exact).
    assert trace.speed_kmh == pytest.approx([100.0, 200.0, 300.0])
    assert len(trace.acceleration_ms2) == 3


# ---- detect_corners ----

def test_detect_corners_no_data_returns_empty() -> None:
    assert detect_corners([], []) == []


def test_detect_corners_finds_a_clear_braking_zone() -> None:
    # Speed ramps up, drops sharply to a clear minimum (corner), ramps back up.
    distance = list(range(0, 400, 20))  # 20 points, spacing 20m
    speed = [300] * 5 + [280, 220, 150, 90, 90] + [150, 220, 280, 300, 300, 300, 300, 300, 300, 300]
    corners = detect_corners(distance, speed, min_spacing_m=50.0, min_prominence_kmh=15.0)
    assert len(corners) == 1
    assert corners[0].apex_speed_kmh == 90


def test_detect_corners_ignores_minor_speed_wobble() -> None:
    distance = list(range(0, 200, 20))
    speed = [300, 298, 300, 299, 300, 298, 300, 299, 300, 300]  # noise under the prominence threshold
    corners = detect_corners(distance, speed, min_prominence_kmh=15.0)
    assert corners == []


def test_detect_corners_collapses_nearby_minima_to_the_deepest() -> None:
    distance = [0, 10, 20, 30, 40, 50, 60]
    speed = [300, 200, 210, 190, 220, 300, 300]  # two close minima (200, 190) within min_spacing
    corners = detect_corners(distance, speed, min_spacing_m=50.0, min_prominence_kmh=15.0)
    assert len(corners) == 1
    assert corners[0].apex_speed_kmh == 190  # the deeper of the two


# ---- compute_delta_trace ----

def test_delta_trace_empty_laps_returns_empty() -> None:
    result = compute_delta_trace(LapTrace(), LapTrace())
    assert result.distance_m == []
    assert result.delta_seconds == []


def test_delta_trace_identical_laps_is_zero_everywhere() -> None:
    lap = LapTrace(
        distance_m=[0, 100, 200, 300],
        time_ms=[0, 4000, 8000, 12000],
        speed_kmh=[300, 200, 250, 300],
    )
    result = compute_delta_trace(lap, lap)
    assert all(abs(d) < 1e-9 for d in result.delta_seconds)


def test_delta_trace_positive_when_b_is_slower() -> None:
    # A covers the lap in half the time B does at every point -> B is always behind (positive delta).
    lap_a = LapTrace(distance_m=[0, 100, 200], time_ms=[0, 1000, 2000], speed_kmh=[300, 300, 300])
    lap_b = LapTrace(distance_m=[0, 100, 200], time_ms=[0, 2000, 4000], speed_kmh=[150, 150, 150])
    result = compute_delta_trace(lap_a, lap_b)
    assert all(d > 0 for d in result.delta_seconds[1:])  # first point is always ~0 (both start together)


def test_delta_trace_caps_to_shorter_laps_distance() -> None:
    lap_a = LapTrace(distance_m=[0, 100], time_ms=[0, 1000], speed_kmh=[300, 300])
    lap_b = LapTrace(distance_m=[0, 50], time_ms=[0, 500], speed_kmh=[300, 300])
    result = compute_delta_trace(lap_a, lap_b)
    assert max(result.distance_m) == pytest.approx(50.0)
