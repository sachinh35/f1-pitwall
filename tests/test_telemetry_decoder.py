"""Golden-file tests for utils/telemetry_decoder.py against real captured F1 payloads."""
import base64
import json
import zlib
from pathlib import Path

from utils.telemetry_decoder import (
    CHANNEL_BRAKE_PCT,
    CHANNEL_DRS,
    CHANNEL_GEAR,
    CHANNEL_RPM,
    CHANNEL_SPEED_KMH,
    CHANNEL_THROTTLE_PCT,
    decode_car_data,
    decode_position,
)

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "real_stream_samples.json").read_text())


def test_decode_car_data_matches_independently_decoded_payload() -> None:
    frame = decode_car_data(FIXTURES["car_data_raw_payload"])
    assert len(frame.samples) >= 1

    first = frame.samples[0]
    expected_cars = FIXTURES["car_data_expected_first_entry_cars"]

    for driver_str, expected in expected_cars.items():
        driver_number = int(driver_str)
        assert driver_number in first.cars
        decoded = first.cars[driver_number]
        channels = expected["Channels"]
        assert decoded.rpm == channels.get(CHANNEL_RPM, 0)
        assert decoded.speed_kmh == channels.get(CHANNEL_SPEED_KMH, 0)
        assert decoded.gear == channels.get(CHANNEL_GEAR, 0)
        assert decoded.throttle_pct == channels.get(CHANNEL_THROTTLE_PCT, 0)
        assert decoded.brake_pct == channels.get(CHANNEL_BRAKE_PCT, 0)
        assert decoded.drs == channels.get(CHANNEL_DRS, 0)


def test_decode_car_data_parses_utc_timestamp() -> None:
    frame = decode_car_data(FIXTURES["car_data_raw_payload"])
    expected_prefix = FIXTURES["car_data_expected_first_entry_utc"][:19]
    assert frame.samples[0].utc.isoformat().startswith(expected_prefix)


def test_decode_position_matches_independently_decoded_payload() -> None:
    frame = decode_position(FIXTURES["position_raw_payload"])
    assert len(frame.samples) >= 1

    first = frame.samples[0]
    expected_entries = FIXTURES["position_expected_first_entry_entries"]

    for driver_str, expected in expected_entries.items():
        driver_number = int(driver_str)
        assert driver_number in first.cars
        decoded = first.cars[driver_number]
        assert decoded.status == expected["Status"]
        assert decoded.x == expected["X"]
        assert decoded.y == expected["Y"]
        assert decoded.z == expected["Z"]


def _compress_raw_deflate(data: dict) -> str:
    """Build a base64+raw-deflate payload the same way F1's feed encodes one, for synthetic edge-case tests."""
    raw_json = json.dumps(data).encode()
    compressor = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
    compressed = compressor.compress(raw_json) + compressor.flush()
    return base64.b64encode(compressed).decode()


def test_decode_car_data_defaults_missing_channels_to_zero() -> None:
    payload = _compress_raw_deflate(
        {"Entries": [{"Utc": "2025-01-01T00:00:00.000Z", "Cars": {"44": {"Channels": {"2": 250}}}}]}
    )
    frame = decode_car_data(payload)
    car = frame.samples[0].cars[44]
    assert car.speed_kmh == 250
    assert car.rpm == 0
    assert car.gear == 0
    assert car.drs_active is False


def test_decode_car_data_drs_active_property() -> None:
    payload = _compress_raw_deflate(
        {"Entries": [{"Utc": "2025-01-01T00:00:00.000Z", "Cars": {"1": {"Channels": {"45": 12}}}}]}
    )
    frame = decode_car_data(payload)
    assert frame.samples[0].cars[1].drs_active is True


def test_decode_position_handles_multiple_cars() -> None:
    payload = _compress_raw_deflate(
        {
            "Position": [
                {
                    "Timestamp": "2025-01-01T00:00:00.000Z",
                    "Entries": {
                        "1": {"Status": "OnTrack", "X": 100, "Y": -200, "Z": 50},
                        "44": {"Status": "OffTrack", "X": -300, "Y": 400, "Z": 60},
                    },
                }
            ]
        }
    )
    frame = decode_position(payload)
    assert frame.samples[0].cars[1].status == "OnTrack"
    assert frame.samples[0].cars[44].x == -300
