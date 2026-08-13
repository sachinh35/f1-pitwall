"""
Lap-to-lap telemetry comparison: distance-aligned speed/throttle/brake
traces, derived acceleration, inferred corner locations, and the classic
"gaining/losing time" delta trace race engineers use.

Built entirely from what's already captured in lap_telemetry/lap_car_position
(CarData.z + Position.z, resolved per completed lap) - no extra live-feed
dependency, so this works for any two completed laps, live session or
historical, the moment both are in Postgres.

F1's feed gives neither a distance-along-lap channel nor corner locations.
Both are derived here:
  - distance comes from integrating consecutive Position.z X/Y samples.
  - corners are inferred as local minima in the speed trace (every corner
    entry involves braking to some apex speed before accelerating away).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

import numpy as np

# Corner-detection tuning: prominence filters out minor speed wobbles that
# aren't a real corner; spacing collapses multiple noisy minima found inside
# the same physical corner into one.
DEFAULT_MIN_CORNER_SPACING_M: float = 80.0
DEFAULT_MIN_CORNER_PROMINENCE_KMH: float = 15.0
_LOCAL_MAX_WINDOW: int = 10

# Number of points the delta trace is resampled onto - a fixed, dense grid
# makes two laps of different sample counts directly comparable.
DELTA_TRACE_POINTS: int = 200


@dataclass
class LapTrace:
    """One driver's one lap, with telemetry resampled onto Position.z's own timestamp/distance axis."""
    distance_m: List[float] = field(default_factory=list)
    time_ms: List[float] = field(default_factory=list)
    speed_kmh: List[float] = field(default_factory=list)
    throttle_pct: List[float] = field(default_factory=list)
    brake_pct: List[float] = field(default_factory=list)
    acceleration_ms2: List[float] = field(default_factory=list)


@dataclass
class Corner:
    """A detected corner (speed local minimum), located by distance along the lap."""
    distance_m: float
    apex_speed_kmh: float


@dataclass
class DeltaTrace:
    """Driver B's cumulative time gained(-)/lost(+) relative to driver A, at each distance point.

    Positive = B is behind where A was at that point on track (losing time); negative = B is ahead."""
    distance_m: List[float] = field(default_factory=list)
    delta_seconds: List[float] = field(default_factory=list)
    corners: List[Corner] = field(default_factory=list)


def compute_cumulative_distance(x: Sequence[int], y: Sequence[int]) -> List[float]:
    """Cumulative 2D track distance from consecutive position samples (arbitrary F1 telemetry units, not metres)."""
    if len(x) == 0:
        return []
    distances = [0.0]
    for i in range(1, len(x)):
        dx = x[i] - x[i - 1]
        dy = y[i] - y[i - 1]
        distances.append(distances[-1] + (dx * dx + dy * dy) ** 0.5)
    return distances


def compute_acceleration(time_ms: Sequence[float], speed_kmh: Sequence[float]) -> List[float]:
    """
    Longitudinal acceleration (m/s^2) via finite difference of speed over time.
    F1's feed samples at roughly 3-4Hz, not a dedicated high-rate
    accelerometer channel - expect a visibly steppier trace than
    broadcast-grade telemetry, which samples far faster.
    """
    n = len(speed_kmh)
    if n == 0:
        return []
    accel = [0.0]
    for i in range(1, n):
        dt_s = (time_ms[i] - time_ms[i - 1]) / 1000.0
        if dt_s <= 0:
            accel.append(accel[-1])
            continue
        dv_ms = (speed_kmh[i] - speed_kmh[i - 1]) / 3.6
        accel.append(dv_ms / dt_s)
    return accel


def build_lap_trace(
    position_dt_ms: Sequence[int],
    x: Sequence[int],
    y: Sequence[int],
    telemetry_dt_ms: Sequence[int],
    speed_kmh: Sequence[int],
    throttle_pct: Sequence[int],
    brake_pct: Sequence[int],
) -> LapTrace:
    """
    Resample the telemetry channels (CarData.z, its own timestamp axis) onto
    Position.z's timestamp axis via linear interpolation, so distance,
    speed, throttle and brake are all directly comparable at the same
    instant. The two topics arrive as separate SignalR messages with
    independent per-lap zero points, so they aren't naturally aligned.

    Returns an empty LapTrace if either input is empty (nothing to compare).
    """
    if len(position_dt_ms) == 0 or len(telemetry_dt_ms) == 0:
        return LapTrace()

    distance = compute_cumulative_distance(x, y)
    time_ms = [float(t) for t in position_dt_ms]

    speed_on_position_axis = np.interp(time_ms, telemetry_dt_ms, speed_kmh).tolist()
    throttle_on_position_axis = np.interp(time_ms, telemetry_dt_ms, throttle_pct).tolist()
    brake_on_position_axis = np.interp(time_ms, telemetry_dt_ms, brake_pct).tolist()

    acceleration = compute_acceleration(time_ms, speed_on_position_axis)

    return LapTrace(
        distance_m=distance,
        time_ms=time_ms,
        speed_kmh=speed_on_position_axis,
        throttle_pct=throttle_on_position_axis,
        brake_pct=brake_on_position_axis,
        acceleration_ms2=acceleration,
    )


def detect_corners(
    distance_m: Sequence[float],
    speed_kmh: Sequence[float],
    min_spacing_m: float = DEFAULT_MIN_CORNER_SPACING_M,
    min_prominence_kmh: float = DEFAULT_MIN_CORNER_PROMINENCE_KMH,
) -> List[Corner]:
    """Locate corners as local minima in the speed trace - see module docstring for why this is the only option."""
    n = len(speed_kmh)
    if n < 3:
        return []

    candidates = [i for i in range(1, n - 1) if speed_kmh[i] < speed_kmh[i - 1] and speed_kmh[i] <= speed_kmh[i + 1]]

    corners: List[Corner] = []
    for idx in candidates:
        left = max(0, idx - _LOCAL_MAX_WINDOW)
        right = min(n, idx + _LOCAL_MAX_WINDOW)
        local_max = max(speed_kmh[left:right])
        if local_max - speed_kmh[idx] < min_prominence_kmh:
            continue

        if corners and (distance_m[idx] - corners[-1].distance_m) < min_spacing_m:
            if speed_kmh[idx] < corners[-1].apex_speed_kmh:
                corners[-1] = Corner(distance_m=distance_m[idx], apex_speed_kmh=speed_kmh[idx])
            continue

        corners.append(Corner(distance_m=distance_m[idx], apex_speed_kmh=speed_kmh[idx]))

    return corners


def compute_delta_trace(lap_a: LapTrace, lap_b: LapTrace) -> DeltaTrace:
    """
    The "gaining/losing time" trace: at each distance point (a common grid
    capped to the shorter of the two laps' recorded distance), how much more
    or less time driver B has taken to reach that point versus driver A.
    Corners are located from driver A's speed trace (the reference lap).
    """
    if not lap_a.distance_m or not lap_b.distance_m:
        return DeltaTrace()

    max_distance = min(lap_a.distance_m[-1], lap_b.distance_m[-1])
    if max_distance <= 0:
        return DeltaTrace()

    common_distance = np.linspace(0, max_distance, num=DELTA_TRACE_POINTS)
    time_a = np.interp(common_distance, lap_a.distance_m, lap_a.time_ms) / 1000.0
    time_b = np.interp(common_distance, lap_b.distance_m, lap_b.time_ms) / 1000.0
    delta = (time_b - time_a).tolist()

    corners = detect_corners(lap_a.distance_m, lap_a.speed_kmh)

    return DeltaTrace(distance_m=common_distance.tolist(), delta_seconds=delta, corners=corners)
