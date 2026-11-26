"""Nuki Opener Bluetooth LE protocol (pairing, encrypted commands).

Implements the public Nuki BLE API: unencrypted pairing over the pairing GDIO
characteristic and XSalsa20-Poly1305 encrypted messages over the USDIO
characteristic. Has no Home Assistant dependencies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import logging
import os
import struct
from types import TracebackType

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from nacl.bindings import crypto_box_beforenm
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey
from nacl.secret import SecretBox

from .const import (
    ERROR_BUSY,
    ERROR_CODES,
    KEYTURNER_USDIO_UUID,
    PAIRING_GDIO_UUID,
    ClientType,
    Command,
    OpenerAction,
    Status,
)
from .models import (
    BatteryReport,
    LogEntry,
    OpenerAdvancedConfig,
    OpenerConfig,
    OpenerState,
)

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 10.0
ACTION_TIMEOUT = 30.0
LOG_IDLE_TIMEOUT = 3.0
BUSY_RETRIES = 2
ENCRYPTED_HEADER_LEN = 24 + 4 + 2  # nonce + auth id + length

UNENCRYPTED_PAYLOAD_LENGTHS: dict[int, int] = {
    Command.PUBLIC_KEY: 32,
    Command.CHALLENGE: 32,
    Command.AUTHORIZATION_ID: 32 + 4 + 16 + 32,
    Command.STATUS: 1,
    Command.ERROR_REPORT: 3,
}


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


@dataclass(slots=True)
class PairingResult:
    auth_id: int
    shared_key: bytes
    app_id: int


# --- connection ----------------------------------------------------------------


class _Session:
    """One BLE connection with a subscribed characteristic and a message queue."""

    def __init__(self, client: BleakClient, char_uuid: str, key: bytes | None) -> None:
        self.client = client
        self._char = char_uuid
        self._reassembler = _Reassembler(key)
        self._queue: asyncio.Queue[tuple[int, bytes] | Exception] = asyncio.Queue()
        # Keyturner states pushed by the device while waiting for something else.
        self.unsolicited_states: list[bytes] = []

    async def start(self) -> None:
        await self.client.start_notify(self._char, self._on_data)

    def _on_data(self, _sender: object, data: bytearray) -> None:
        try:
            for msg in self._reassembler.feed(bytes(data)):
                self._queue.put_nowait(msg)
        except NukiError as err:
            self._queue.put_nowait(err)

    async def write(self, data: bytes) -> None:
        await self.client.write_gatt_char(self._char, data, response=True)

    async def next_message(self, timeout: float) -> tuple[int, bytes]:
        """Return the next message, raising on ERROR_REPORT."""
        async with asyncio.timeout(timeout):
            item = await self._queue.get()
        if isinstance(item, Exception):
            raise item
        command, payload = item
        if command == Command.ERROR_REPORT:
            code = payload[0]
            raise NukiDeviceError(code, struct.unpack_from("<H", payload, 1)[0])
        return command, payload

    async def receive(self, expected: int, timeout: float = RESPONSE_TIMEOUT) -> bytes:
        """Wait for a message with the given command."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            command, payload = await self.next_message(max(deadline - loop.time(), 0.01))
            if command == expected:
                return payload
            if command == Command.KEYTURNER_STATES:
                self.unsolicited_states.append(payload)
            _LOGGER.debug("Ignoring 0x%04X while waiting for 0x%04X", command, expected)


class _Connection:
    """Async context manager: connect, subscribe, always disconnect."""

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
        except Exception as err:
            await self._close()
            if isinstance(err, NukiError):
                raise
            raise NukiError(f"Bluetooth error: {err}") from err
        return session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
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


# --- authorized client -----------------------------------------------------------


class OpenerSession:
    """Commands available while connected to a paired Opener."""

    def __init__(self, session: _Session, auth_id: int, key: bytes, app_id: int, pin: int | None) -> None:
        self._s = session
        self._auth_id = auth_id
        self._key = key
        self._app_id = app_id
        self._pin = pin

    @property
    def unsolicited_states(self) -> list[bytes]:
        return self._s.unsolicited_states

    async def _send(self, command: int, payload: bytes = b"") -> None:
        await self._s.write(build_encrypted(self._key, self._auth_id, command, payload))

    async def _request(self, command: int) -> bytes:
        await self._send(Command.REQUEST_DATA, struct.pack("<H", command))
        return await self._s.receive(command)

    async def _challenge(self) -> bytes:
        return await self._request(Command.CHALLENGE)

    def _pin_bytes(self) -> bytes:
        if self._pin is None:
            raise NukiError("This command requires the Opener security PIN (set it in the integration options)")
        return struct.pack("<H", self._pin)

    async def _with_challenge(self, command: int, payload: bytes = b"", pin: bool = False) -> None:
        nonce = await self._challenge()
        await self._send(command, payload + nonce + (self._pin_bytes() if pin else b""))

    async def _expect_complete(self, timeout: float = RESPONSE_TIMEOUT) -> None:
        status = await self._s.receive(Command.STATUS, timeout)
        if status[0] != Status.COMPLETE:
            raise NukiError(f"Unexpected status 0x{status[0]:02X}")

    # reads -----------------------------------------------------------------

    async def state(self) -> OpenerState:
        return OpenerState.parse(await self._request(Command.KEYTURNER_STATES))

    async def battery_report(self) -> BatteryReport:
        return BatteryReport.parse(await self._request(Command.BATTERY_REPORT))

    async def config(self) -> OpenerConfig:
        await self._with_challenge(Command.REQUEST_CONFIG)
        return OpenerConfig.parse(await self._s.receive(Command.CONFIG))

    async def advanced_config(self) -> OpenerAdvancedConfig:
        await self._with_challenge(Command.REQUEST_ADVANCED_CONFIG)
        return OpenerAdvancedConfig.parse(await self._s.receive(Command.ADVANCED_CONFIG))

    async def log_entries(self, count: int, start_index: int = 0) -> list[LogEntry]:
        """Most recent log entries, newest first (requires PIN)."""
        payload = struct.pack("<IHBB", start_index, count, 1, 0)  # descending, no count
        await self._with_challenge(Command.REQUEST_LOG_ENTRIES, payload, pin=True)
        entries: list[LogEntry] = []
        timeout = RESPONSE_TIMEOUT
        while len(entries) < count:
            try:
                command, data = await self._s.next_message(timeout)
            except TimeoutError:
                if entries:
                    break
                raise
            timeout = LOG_IDLE_TIMEOUT
            if command == Command.LOG_ENTRY:
                entries.append(LogEntry.parse(data))
            elif command == Command.STATUS:
                break
        return entries

    # writes ----------------------------------------------------------------

    async def lock_action(self, action: OpenerAction) -> None:
        if action in (OpenerAction.ACTIVATE_CM, OpenerAction.DEACTIVATE_CM) and self._pin is not None:
            # Newer firmware only honours continuous mode through this command.
            enabled = 1 if action == OpenerAction.ACTIVATE_CM else 0
            await self._with_challenge(
                Command.CONTINUOUS_MODE_ACTION, struct.pack("<BB", enabled, 0), pin=True
            )
        else:
            await self._with_challenge(
                Command.LOCK_ACTION, struct.pack("<BIB", action, self._app_id, 0)
            )
        if (await self._s.receive(Command.STATUS))[0] == Status.ACCEPTED:
            await self._expect_complete(ACTION_TIMEOUT)

    async def set_config(self, payload: bytes) -> None:
        await self._with_challenge(Command.SET_CONFIG, payload, pin=True)
        await self._expect_complete()

    async def set_advanced_config(self, payload: bytes) -> None:
        await self._with_challenge(Command.SET_ADVANCED_CONFIG, payload, pin=True)
        await self._expect_complete()

    async def verify_pin(self) -> None:
        await self._with_challenge(Command.VERIFY_SECURITY_PIN, pin=True)
        await self._expect_complete()

    async def update_time(self, when: datetime | None = None) -> None:
        now = (when or datetime.now(UTC)).astimezone(UTC)
        payload = struct.pack(
            "<HBBBBB", now.year, now.month, now.day, now.hour, now.minute, now.second
        )
        await self._with_challenge(Command.UPDATE_TIME, payload, pin=True)
        await self._expect_complete()

    async def reboot(self) -> None:
        await self._with_challenge(Command.REQUEST_REBOOT, pin=True)
        await self._expect_complete()


class NukiOpenerClient:
    """Opens a connection to a paired Opener and runs a coroutine in it."""

    def __init__(self, auth_id: int, shared_key: bytes, app_id: int, pin: int | None = None) -> None:
        self.auth_id = auth_id
        self.shared_key = shared_key
        self.app_id = app_id
        self.pin = pin

    async def run[T](
        self,
        device: BLEDevice,
        device_callback: Callable[[], BLEDevice] | None,
        job: Callable[[OpenerSession], Awaitable[T]],
    ) -> T:
        """Connect, run `job(session)`, disconnect. Retries when the Opener is busy."""
        for attempt in range(BUSY_RETRIES + 1):
            try:
                async with _Connection(
                    device, device_callback, KEYTURNER_USDIO_UUID, self.shared_key
                ) as raw:
                    session = OpenerSession(raw, self.auth_id, self.shared_key, self.app_id, self.pin)
                    return await job(session)
            except NukiDeviceError as err:
                if err.code != ERROR_BUSY or attempt == BUSY_RETRIES:
                    raise
                _LOGGER.debug("Opener busy, retrying")
                await asyncio.sleep(1 + attempt)
        raise NukiError("unreachable")


async def async_pair(
    device: BLEDevice, client_name: str, client_type: ClientType = ClientType.APP
) -> PairingResult:
    """Pair with an Opener that is in pairing mode and return the credentials."""
    app_id = struct.unpack("<I", os.urandom(4))[0]
    secret = PrivateKey.generate()
    client_pk = bytes(secret.public_key)

    async with _Connection(device, None, PAIRING_GDIO_UUID, None) as session:

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
