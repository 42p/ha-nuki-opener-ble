"""Nuki Opener Bluetooth LE protocol (pairing, encrypted commands, state parsing).

Implements the public Nuki BLE API: unencrypted pairing over the pairing GDIO
characteristic and XSalsa20-Poly1305 encrypted messages over the USDIO
characteristic. Has no Home Assistant dependencies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import logging
import os
import struct

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from nacl.bindings import crypto_box_beforenm
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey
from nacl.secret import SecretBox

from .const import (
    ERROR_CODES,
    KEYTURNER_USDIO_UUID,
    PAIRING_GDIO_UUID,
    UNENCRYPTED_PAYLOAD_LENGTHS,
    ClientType,
    Command,
    OpenerAction,
    OpenerLockState,
    OpenerMode,
    Status,
)

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 10.0
ACTION_TIMEOUT = 30.0
ENCRYPTED_HEADER_LEN = 24 + 4 + 2  # nonce + auth id + length


class NukiError(Exception):
    """Generic Nuki communication error."""


class NukiDeviceError(NukiError):
    """The device answered with an ERROR_REPORT."""

    def __init__(self, code: int, command: int) -> None:
        self.code = code
        self.command = command
        text = ERROR_CODES.get(code, "unknown")
        super().__init__(f"Nuki error 0x{code:02X} ({text}) for command 0x{command:04X}")


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


# --- message framing ---------------------------------------------------------


def build_unencrypted(command: int, payload: bytes = b"") -> bytes:
    """Build a plain message: command + payload + CRC."""
    body = struct.pack("<H", command) + payload
    return body + struct.pack("<H", crc16(body))


def build_encrypted(key: bytes, auth_id: int, command: int, payload: bytes = b"") -> bytes:
    """Build an encrypted message: nonce + auth id + length + secretbox(pdata)."""
    pdata = struct.pack("<IH", auth_id, command) + payload
    pdata += struct.pack("<H", crc16(pdata))
    nonce = os.urandom(24)
    ciphertext = SecretBox(key).encrypt(pdata, nonce).ciphertext
    return nonce + struct.pack("<IH", auth_id, len(ciphertext)) + ciphertext


def decrypt_message(key: bytes, data: bytes) -> tuple[int, bytes]:
    """Decrypt a complete encrypted message and return (command, payload)."""
    nonce = data[:24]
    length = struct.unpack_from("<H", data, 28)[0]
    ciphertext = data[ENCRYPTED_HEADER_LEN : ENCRYPTED_HEADER_LEN + length]
    try:
        pdata = SecretBox(key).decrypt(ciphertext, nonce)
    except CryptoError as err:
        raise NukiError("Unable to decrypt message (wrong key?)") from err
    if crc16(pdata[:-2]) != struct.unpack("<H", pdata[-2:])[0]:
        raise NukiError("Bad CRC in decrypted message")
    command = struct.unpack_from("<H", pdata, 4)[0]
    return command, pdata[6:-2]


class _Reassembler:
    """Collects indication fragments into complete messages."""

    def __init__(self, key: bytes | None) -> None:
        self._key = key
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        self._buf.extend(chunk)
        messages: list[tuple[int, bytes]] = []
        while msg := self._take():
            messages.append(msg)
        return messages

    def _take(self) -> tuple[int, bytes] | None:
        buf = self._buf
        if self._key is not None:
            if len(buf) < ENCRYPTED_HEADER_LEN:
                return None
            total = ENCRYPTED_HEADER_LEN + struct.unpack_from("<H", buf, 28)[0]
            if len(buf) < total:
                return None
            raw = bytes(buf[:total])
            del buf[:total]
            return decrypt_message(self._key, raw)

        if len(buf) < 4:
            return None
        command = struct.unpack_from("<H", buf, 0)[0]
        if (plen := UNENCRYPTED_PAYLOAD_LENGTHS.get(command)) is not None:
            total = 2 + plen + 2
            if len(buf) < total:
                return None
        else:
            # Unknown command: find the first prefix with a valid CRC.
            total = next(
                (
                    n
                    for n in range(4, len(buf) + 1)
                    if crc16(buf[: n - 2]) == struct.unpack_from("<H", buf, n - 2)[0]
                ),
                0,
            )
            if not total:
                return None
        raw = bytes(buf[:total])
        del buf[:total]
        if crc16(raw[:-2]) != struct.unpack("<H", raw[-2:])[0]:
            raise NukiError("Bad CRC in unencrypted message")
        return command, raw[2:-2]


# --- state -------------------------------------------------------------------


@dataclass(slots=True)
class OpenerState:
    """Parsed Opener keyturner states."""

    mode: OpenerMode | int
    lock_state: OpenerLockState | int
    trigger: int
    device_time: datetime | None
    battery_critical: bool
    ring_to_open_timer: int | None = None
    last_action: int | None = None
    last_action_trigger: int | None = None
    last_action_completion: int | None = None

    @property
    def ring_to_open(self) -> bool:
        return self.lock_state == OpenerLockState.RTO_ACTIVE

    @property
    def continuous_mode(self) -> bool:
        return self.mode == OpenerMode.CONTINUOUS

    @classmethod
    def parse(cls, payload: bytes) -> OpenerState:
        if len(payload) < 13:
            raise NukiError(f"Keyturner states too short ({len(payload)} bytes)")
        mode, lock, trigger, year, mon, day, hour, minute, sec, _tz, battery = (
            struct.unpack_from("<BBBHBBBBBhB", payload)
        )
        try:
            device_time = datetime(year, mon, day, hour, minute, sec)
        except ValueError:
            device_time = None
        extra = list(payload[13:18]) + [None] * 5
        return cls(
            mode=_enum_or_int(OpenerMode, mode),
            lock_state=_enum_or_int(OpenerLockState, lock),
            trigger=trigger,
            device_time=device_time,
            battery_critical=bool(battery & 0x01),
            ring_to_open_timer=extra[1],
            last_action=extra[2],
            last_action_trigger=extra[3],
            last_action_completion=extra[4],
        )


def _enum_or_int(enum_cls, value: int):
    try:
        return enum_cls(value)
    except ValueError:
        return value


@dataclass(slots=True)
class PairingResult:
    auth_id: int
    shared_key: bytes
    app_id: int


# --- session -----------------------------------------------------------------


class _Session:
    """One BLE connection with a subscribed characteristic and a message queue."""

    def __init__(self, client: BleakClient, char_uuid: str, key: bytes | None) -> None:
        self._client = client
        self._char = char_uuid
        self._reassembler = _Reassembler(key)
        self._queue: asyncio.Queue[tuple[int, bytes] | Exception] = asyncio.Queue()

    async def start(self) -> None:
        await self._client.start_notify(self._char, self._on_data)

    def _on_data(self, _sender, data: bytearray) -> None:
        try:
            for msg in self._reassembler.feed(bytes(data)):
                self._queue.put_nowait(msg)
        except NukiError as err:
            self._queue.put_nowait(err)

    async def write(self, data: bytes) -> None:
        await self._client.write_gatt_char(self._char, data, response=True)

    async def receive(self, expected: int, timeout: float = RESPONSE_TIMEOUT) -> bytes:
        """Wait for a message with the given command, raising on ERROR_REPORT."""
        async with asyncio.timeout(timeout):
            while True:
                item = await self._queue.get()
                if isinstance(item, Exception):
                    raise item
                command, payload = item
                if command == Command.ERROR_REPORT:
                    code = struct.unpack_from("<b", payload)[0] & 0xFF
                    raise NukiDeviceError(code, struct.unpack_from("<H", payload, 1)[0])
                if command == expected:
                    return payload
                _LOGGER.debug("Ignoring command 0x%04X while waiting for 0x%04X", command, expected)


class NukiOpenerClient:
    """High level client for a paired Opener."""

    def __init__(self, auth_id: int, shared_key: bytes, app_id: int) -> None:
        self._auth_id = auth_id
        self._key = shared_key
        self._app_id = app_id

    async def _send(self, session: _Session, command: int, payload: bytes = b"") -> None:
        await session.write(build_encrypted(self._key, self._auth_id, command, payload))

    async def _read_state(self, session: _Session) -> OpenerState:
        await self._send(session, Command.REQUEST_DATA, struct.pack("<H", Command.KEYTURNER_STATES))
        return OpenerState.parse(await session.receive(Command.KEYTURNER_STATES))

    async def get_state(
        self, device: BLEDevice, device_callback: Callable[[], BLEDevice] | None = None
    ) -> OpenerState:
        async with _connect(device, device_callback, KEYTURNER_USDIO_UUID, self._key) as session:
            return await self._read_state(session)

    async def lock_action(
        self,
        device: BLEDevice,
        action: OpenerAction,
        device_callback: Callable[[], BLEDevice] | None = None,
    ) -> OpenerState:
        """Execute an action and return the state read afterwards."""
        async with _connect(device, device_callback, KEYTURNER_USDIO_UUID, self._key) as session:
            await self._send(session, Command.REQUEST_DATA, struct.pack("<H", Command.CHALLENGE))
            nonce = await session.receive(Command.CHALLENGE)
            await self._send(
                session,
                Command.LOCK_ACTION,
                struct.pack("<BIB", action, self._app_id, 0) + nonce,
            )
            if (await session.receive(Command.STATUS))[0] == Status.ACCEPTED:
                status = await session.receive(Command.STATUS, ACTION_TIMEOUT)
                if status[0] != Status.COMPLETE:
                    raise NukiError(f"Unexpected action status 0x{status[0]:02X}")
            return await self._read_state(session)


async def async_pair(
    device: BLEDevice, client_name: str, client_type: ClientType = ClientType.APP
) -> PairingResult:
    """Pair with an Opener that is in pairing mode and return the credentials."""
    app_id = struct.unpack("<I", os.urandom(4))[0]
    secret = PrivateKey.generate()
    client_pk = bytes(secret.public_key)

    async with _connect(device, None, PAIRING_GDIO_UUID, None) as session:

        async def send(command: int, payload: bytes = b"") -> None:
            await session.write(build_unencrypted(command, payload))

        await send(Command.REQUEST_DATA, struct.pack("<H", Command.PUBLIC_KEY))
        device_pk = await session.receive(Command.PUBLIC_KEY)

        await send(Command.PUBLIC_KEY, client_pk)
        shared_key = crypto_box_beforenm(device_pk, bytes(secret))
        nonce_k = await session.receive(Command.CHALLENGE)

        await send(
            Command.AUTHORIZATION_AUTHENTICATOR,
            _hmac(shared_key, client_pk + device_pk + nonce_k),
        )
        nonce_k = await session.receive(Command.CHALLENGE)

        name = client_name.encode()[:32].ljust(32, b"\x00")
        data = struct.pack("<BI", client_type, app_id) + name + os.urandom(32)
        await send(Command.AUTHORIZATION_DATA, _hmac(shared_key, data + nonce_k) + data)

        auth_payload = await session.receive(Command.AUTHORIZATION_ID)
        auth_id = struct.unpack_from("<I", auth_payload, 32)[0]
        nonce_k = auth_payload[52:84]

        confirmation = struct.pack("<I", auth_id)
        await send(
            Command.AUTHORIZATION_ID_CONFIRMATION,
            _hmac(shared_key, confirmation + nonce_k) + confirmation,
        )
        status = await session.receive(Command.STATUS)
        if status[0] != Status.COMPLETE:
            raise NukiError(f"Pairing not completed, status 0x{status[0]:02X}")

    _LOGGER.debug("Paired with %s, authorization id %s", device.address, auth_id)
    return PairingResult(auth_id=auth_id, shared_key=shared_key, app_id=app_id)


class _connect:
    """Async context manager: connect, subscribe, disconnect."""

    def __init__(
        self,
        device: BLEDevice,
        device_callback: Callable[[], BLEDevice] | None,
        char_uuid: str,
        key: bytes | None,
    ) -> None:
        self._device = device
        self._device_callback = device_callback
        self._char = char_uuid
        self._key = key
        self._client: BleakClient | None = None

    async def __aenter__(self) -> _Session:
        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self._device,
                self._device.name or self._device.address,
                ble_device_callback=self._device_callback,
            )
            session = _Session(self._client, self._char, self._key)
            await session.start()
        except NukiError:
            await self._close()
            raise
        except Exception as err:  # bleak raises a variety of errors
            await self._close()
            raise NukiError(f"Bluetooth error: {err}") from err
        return session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._close()
        if isinstance(exc, TimeoutError):
            raise NukiError("Timed out waiting for the Opener") from exc
        if isinstance(exc, Exception) and not isinstance(exc, NukiError):
            raise NukiError(f"Bluetooth error: {exc}") from exc

    async def _close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Error while disconnecting", exc_info=True)
            self._client = None
