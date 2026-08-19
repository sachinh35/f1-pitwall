"""
Decoders for F1's compressed live-timing telemetry topics.

`CarData.z` and `Position.z` messages are base64-encoded, raw-deflate
compressed JSON. Channel indices on CarData.z are undocumented by F1; the
ones below were determined by decoding real captured payloads
(stream_logs/f1_stream_1764517880_race_qatar.jsonl) and cross-checking
against known values (e.g. speed trap figures matching TimingStats.BestSpeeds
for the same driver at the same time).
"""
from __future__ import annotations

import base64
import json
import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

# CarData.z channel indices (see module docstring for provenance).
CHANNEL_RPM = "0"
CHANNEL_SPEED_KMH = "2"
CHANNEL_GEAR = "3"
CHANNEL_THROTTLE_PCT = "4"
CHANNEL_BRAKE_PCT = "5"
CHANNEL_DRS = "45"

# DRS channel values observed to mean "DRS open", determined from the
# distribution of values across a full race capture: 12 is the dominant
# active code, 10/14 are much rarer single-frame transition states, all
# clearly separated from the overwhelming 0/1/8 "not open" baseline.
DRS_ACTIVE_CODES = frozenset({10, 12, 14})


@dataclass(frozen=True)
class CarChannels:
    """One car's decoded telemetry channels at a single instant."""
    rpm: int
    speed_kmh: int
    gear: int
    throttle_pct: int
    brake_pct: int
    drs: int

    @property
    def drs_active(self) -> bool:
        return self.drs in DRS_ACTIVE_CODES


@dataclass(frozen=True)
class CarDataSample:
    """All cars' channels at a single timestamp."""
    utc: datetime
    cars: Dict[int, CarChannels]


@dataclass(frozen=True)
class CarDataFrame:
    """A decoded CarData.z message - one or more timestamped samples, batched."""
    samples: List[CarDataSample]


@dataclass(frozen=True)
class PositionEntry:
    """One car's track position at a single instant."""
    status: str
    x: int
    y: int
    z: int


@dataclass(frozen=True)
class PositionSample:
    """All cars' positions at a single timestamp."""
    utc: datetime
    cars: Dict[int, PositionEntry]


@dataclass(frozen=True)
class PositionFrame:
    """A decoded Position.z message - one or more timestamped samples, batched."""
    samples: List[PositionSample]


def _inflate_json(payload: str) -> Any:
    """Base64-decode then raw-deflate-decompress an F1 `.z` topic payload into parsed JSON."""
    compressed = base64.b64decode(payload)
    raw = zlib.decompress(compressed, -zlib.MAX_WBITS)
    return json.loads(raw)


def _parse_utc(value: str) -> datetime:
    """Parse F1's UTC timestamp strings (trailing 'Z', variable fractional-second precision)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def decode_car_data(payload: str) -> CarDataFrame:
    """Decode a raw `CarData.z` message payload into typed per-car telemetry samples."""
    decoded = _inflate_json(payload)
    samples: List[CarDataSample] = []
    for entry in decoded.get("Entries", []):
        utc = _parse_utc(entry["Utc"])
        cars: Dict[int, CarChannels] = {}
        for driver_str, car in entry.get("Cars", {}).items():
            channels = car.get("Channels", {})
            cars[int(driver_str)] = CarChannels(
                rpm=channels.get(CHANNEL_RPM, 0),
                speed_kmh=channels.get(CHANNEL_SPEED_KMH, 0),
                gear=channels.get(CHANNEL_GEAR, 0),
                throttle_pct=channels.get(CHANNEL_THROTTLE_PCT, 0),
                brake_pct=channels.get(CHANNEL_BRAKE_PCT, 0),
                drs=channels.get(CHANNEL_DRS, 0),
            )
        samples.append(CarDataSample(utc=utc, cars=cars))
    return CarDataFrame(samples=samples)


def decode_position(payload: str) -> PositionFrame:
    """Decode a raw `Position.z` message payload into typed per-car track positions."""
    decoded = _inflate_json(payload)
    samples: List[PositionSample] = []
    for entry in decoded.get("Position", []):
        utc = _parse_utc(entry["Timestamp"])
        cars: Dict[int, PositionEntry] = {}
        for driver_str, pos in entry.get("Entries", {}).items():
            cars[int(driver_str)] = PositionEntry(
                status=pos.get("Status", "Unknown"),
                x=pos.get("X", 0),
                y=pos.get("Y", 0),
                z=pos.get("Z", 0),
            )
        samples.append(PositionSample(utc=utc, cars=cars))
    return PositionFrame(samples=samples)
