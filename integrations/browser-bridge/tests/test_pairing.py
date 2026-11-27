from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pairing import DeviceStatus, PairingStore
from protocol import PAIRING_ALPHABET, PAIRING_CODE_LENGTH


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_code_has_expected_shape_and_alphabet() -> None:
    store = PairingStore()
    code, ttl = store.create_code()
    assert len(code) == PAIRING_CODE_LENGTH
    assert set(code) <= set(PAIRING_ALPHABET)
    assert ttl == 300.0


def test_code_is_one_time() -> None:
    store = PairingStore()
    code, _ = store.create_code()
    assert store.consume_code(code) is True
    assert store.consume_code(code) is False


def test_code_is_case_and_space_insensitive() -> None:
    store = PairingStore()
    code, _ = store.create_code()
    assert store.consume_code(f"  {code.lower()} ") is True


def test_code_expires_after_ttl() -> None:
    clock = FakeClock()
    store = PairingStore(clock=clock, code_ttl_s=300)
    code, _ = store.create_code()
    clock.now += 301
    assert store.consume_code(code) is False


def test_unknown_code_is_refused() -> None:
    store = PairingStore()
    store.create_code()
    assert store.consume_code("ZZZZZZZZ") is False


def test_device_credential_verifies_and_is_stored_hashed() -> None:
    store = PairingStore()
    device_id, credential = store.issue_device("laptop")
    assert store.verify(device_id, credential) is DeviceStatus.OK
    assert store.verify(device_id, credential + "x") is DeviceStatus.BAD_CREDENTIAL
    record = store.get(device_id)
    assert record is not None
    assert credential not in repr(record)
    assert record.credential_digest != credential


def test_unknown_device_is_reported_as_unknown() -> None:
    store = PairingStore()
    assert store.verify("dev_missing", "anything") is DeviceStatus.UNKNOWN


def test_revocation_is_immediate_and_reported() -> None:
    store = PairingStore()
    device_id, credential = store.issue_device("laptop")
    assert store.revoke(device_id) is True
    assert store.verify(device_id, credential) is DeviceStatus.REVOKED
    assert store.revoke("dev_missing") is False
