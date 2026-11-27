"""One-time pairing codes and hashed device credentials.

Only SHA-256 digests of codes and credentials are stored. Raw values are returned
once (the credential in the `paired` message, the code in the local API response).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from protocol import PAIRING_ALPHABET, PAIRING_CODE_LENGTH, PAIRING_CODE_TTL_S


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DeviceStatus(StrEnum):
    OK = "ok"
    UNKNOWN = "unknown"
    BAD_CREDENTIAL = "bad_credential"
    REVOKED = "revoked"


@dataclass
class DeviceRecord:
    device_id: str
    name: str
    credential_digest: str = field(repr=False)
    revoked: bool = False


class PairingStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        code_ttl_s: float = PAIRING_CODE_TTL_S,
    ) -> None:
        self._clock = clock
        self._code_ttl_s = code_ttl_s
        self._codes: dict[str, float] = {}  # code digest -> expiry
        self._devices: dict[str, DeviceRecord] = {}

    def create_code(self) -> tuple[str, float]:
        """Return a new one-time code and its time-to-live in seconds."""
        now = self._clock()
        self._codes = {d: exp for d, exp in self._codes.items() if exp > now}
        code = "".join(
            secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH)
        )
        self._codes[digest(code)] = now + self._code_ttl_s
        return code, self._code_ttl_s

    def consume_code(self, code: str) -> bool:
        """Accept a code once. Expired, unknown and reused codes are refused."""
        expiry = self._codes.pop(digest(code.strip().upper()), None)
        return expiry is not None and self._clock() < expiry

    def issue_device(self, name: str) -> tuple[str, str]:
        """Register a device. Returns (device_id, credential); the credential is shown once."""
        device_id = "dev_" + secrets.token_hex(8)
        credential = secrets.token_urlsafe(32)
        self._devices[device_id] = DeviceRecord(
            device_id=device_id, name=name, credential_digest=digest(credential)
        )
        return device_id, credential

    def verify(self, device_id: str, credential: str) -> DeviceStatus:
        record = self._devices.get(device_id)
        if record is None:
            return DeviceStatus.UNKNOWN
        if not hmac.compare_digest(digest(credential), record.credential_digest):
            return DeviceStatus.BAD_CREDENTIAL
        if record.revoked:
            return DeviceStatus.REVOKED
        return DeviceStatus.OK

    def revoke(self, device_id: str) -> bool:
        record = self._devices.get(device_id)
        if record is None:
            return False
        record.revoked = True
        return True

    def devices(self) -> list[DeviceRecord]:
        return list(self._devices.values())

    def get(self, device_id: str) -> DeviceRecord | None:
        return self._devices.get(device_id)
