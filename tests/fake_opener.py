"""In-memory Nuki Opener speaking the BLE protocol, for tests."""

from __future__ import annotations

import hashlib
import hmac
import os
import struct

from nacl.bindings import crypto_box_beforenm
from nacl.public import PrivateKey

from custom_components.nuki_opener_ble import protocol as p
from custom_components.nuki_opener_ble.const import Command as C


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


class FakeOpener:
    """Device side of the protocol; replies are split into 20-byte indications."""

    AUTH_ID = 0x11223344

    def __init__(self, pin: int = 1234) -> None:
        self.sk = PrivateKey.generate()
        self.pk = bytes(self.sk.public_key)
        self.key: bytes | None = None
        self.app_id: int | None = None
        self.pin = pin
        self.mode = 2  # door mode
        self.lock_state = 1  # locked
        self.trigger = 0
        self.last_action = 0
        self.challenge: bytes | None = None
        self.led = 1
        self.button = 1
        self.pairing = 1
        self.rto_timeout = 20
        self.strike_duration = 3000
        self.single_press = 1
        self.logs: list[bytes] = []
        self.log_index = 100
        self.time_set: tuple | None = None
        self.commands: list[int] = []

    # --- helpers ---------------------------------------------------------------

    @staticmethod
    def frames(msg: bytes) -> list[bytes]:
        return [msg[i : i + 20] for i in range(0, len(msg), 20)]

    def add_log(self, typ: int, data: bytes, name: str = "Opener") -> None:
        self.log_index += 1
        self.logs.insert(
            0,
            struct.pack("<IHBBBBBI", self.log_index, 2026, 11, 26, 18, 0, 0, 0)
            + name.encode().ljust(32, b"\x00")
            + bytes([typ])
            + data.ljust(8, b"\x00"),
        )

    def state_payload(self) -> bytes:
        return (
            struct.pack(
                "<BBBHBBBBBhBBBBBB",
                self.mode, self.lock_state, self.trigger, 2026, 11, 26, 18, 0, 0, 60,
                0, 7, 0, self.last_action, 0, 0,
            )
            + struct.pack("<H", 0xFFFF)
            + bytes([0xFF] * 5)
            + bytes([0xFF])
        )

    def config_payload(self) -> bytes:
        return struct.pack(
            "<I32sffBBBBHBBBBBhBBBBBBBB3s2sHB",
            0xABCDEF, b"Haustuer".ljust(32, b"\x00"), 52.5, 13.4, 1,
            self.pairing, self.button, self.led, 2026, 11, 26, 18, 0, 0, 60, 1, 0,
            0, 0, 0, 0, 0, 0, bytes([1, 8, 22]), bytes([3, 1]), 37, 0,
        )

    def advanced_payload(self) -> bytes:
        return struct.pack(
            "<HBHHBHBBBBHBBBBBBBBBBB",
            1234, 0, 0, 0, 0, self.strike_duration, 0, self.rto_timeout, 0, 0, 2000,
            1, 1, 1, 1, 1, 128, self.single_press, 0, 0, 1, 1,
        )

    # --- pairing (unencrypted) ---------------------------------------------------

    def unencrypted(self, data: bytes) -> list[bytes]:
        cmd = struct.unpack_from("<H", data)[0]
        assert p.crc16(data[:-2]) == struct.unpack("<H", data[-2:])[0]
        pl = data[2:-2]

        def out(c: int, x: bytes) -> list[bytes]:
            return self.frames(p.build_unencrypted(c, x))

        if cmd == C.REQUEST_DATA:
            return out(C.PUBLIC_KEY, self.pk)
        if cmd == C.PUBLIC_KEY:
            self.cpk = pl
            self.key = crypto_box_beforenm(pl, bytes(self.sk))
            self.nk = os.urandom(32)
            return out(C.CHALLENGE, self.nk)
        if cmd == C.AUTHORIZATION_AUTHENTICATOR:
            assert pl == _hmac(self.key, self.cpk + self.pk + self.nk), "bad authenticator"
            self.nk = os.urandom(32)
            return out(C.CHALLENGE, self.nk)
        if cmd == C.AUTHORIZATION_DATA:
            assert len(pl) == 101
            assert pl[:32] == _hmac(self.key, pl[32:] + self.nk), "bad authorization data"
            self.app_id = struct.unpack_from("<I", pl, 33)[0]
            self.nk = os.urandom(32)
            body = struct.pack("<I", self.AUTH_ID) + os.urandom(16) + self.nk
            return out(C.AUTHORIZATION_ID, _hmac(self.key, body) + body)
        if cmd == C.AUTHORIZATION_ID_CONFIRMATION:
            assert pl[:32] == _hmac(self.key, struct.pack("<I", self.AUTH_ID) + self.nk)
            return out(C.STATUS, b"\x00")
        raise AssertionError(hex(cmd))

    # --- encrypted -----------------------------------------------------------------

    def _out(self, c: int, x: bytes) -> list[bytes]:
        return self.frames(p.build_encrypted(self.key, self.AUTH_ID, c, x))

    def _error(self, code: int, cmd: int) -> list[bytes]:
        return self._out(C.ERROR_REPORT, struct.pack("<BH", code, cmd))

    def _check(self, pl: bytes, pin: bool) -> bytes | None:
        """Strip nonce (+PIN) and validate them; return the body or None on bad PIN."""
        tail = 34 if pin else 32
        body, nonce = pl[:-tail], pl[len(pl) - tail : len(pl) - tail + 32]
        assert nonce == self.challenge, "challenge nonce not echoed"
        self.challenge = None
        if pin and struct.unpack("<H", pl[-2:])[0] != self.pin:
            return None
        return body

    def encrypted(self, data: bytes) -> list[bytes]:
        cmd, pl = p.decrypt_message(self.key, data)
        self.commands.append(cmd)
        out, ok = self._out, self._out(C.STATUS, b"\x00")

        if cmd == C.REQUEST_DATA:
            want = struct.unpack("<H", pl)[0]
            if want == C.CHALLENGE:
                self.challenge = os.urandom(32)
                return out(C.CHALLENGE, self.challenge)
            if want == C.KEYTURNER_STATES:
                return out(C.KEYTURNER_STATES, self.state_payload())
            if want == C.BATTERY_REPORT:
                return out(C.BATTERY_REPORT, struct.pack("<HHBBHHHbHH", 10, 4712, 0, 0, 0, 0, 0, 20, 0, 0))
            raise AssertionError(hex(want))
        if cmd == C.REQUEST_CONFIG:
            self._check(pl, False)
            return out(C.CONFIG, self.config_payload())
        if cmd == C.REQUEST_ADVANCED_CONFIG:
            self._check(pl, False)
            return out(C.ADVANCED_CONFIG, self.advanced_payload())
        if cmd == C.LOCK_ACTION:
            body = self._check(pl, False)
            action, app_id, _flags = struct.unpack("<BIB", body)
            assert app_id == self.app_id
            self.last_action = action
            self.trigger = 0
            if action == 0x01:
                self.lock_state = 3
            elif action == 0x02:
                self.lock_state = 1
            elif action == 0x03:
                self.lock_state = 5
            elif action == 0x04:
                self.mode = 3
            elif action == 0x05:
                self.mode = 2
            return out(C.STATUS, b"\x01") + out(C.KEYTURNER_STATES, self.state_payload()) + ok
        pin_commands = {
            C.CONTINUOUS_MODE_ACTION, C.SET_CONFIG, C.SET_ADVANCED_CONFIG,
            C.VERIFY_SECURITY_PIN, C.UPDATE_TIME, C.REQUEST_LOG_ENTRIES, C.REQUEST_REBOOT,
        }
        if cmd in pin_commands:
            body = self._check(pl, True)
            if body is None:
                return self._error(0x21, cmd)
            if cmd == C.CONTINUOUS_MODE_ACTION:
                self.mode = 3 if body[0] else 2
                return ok
            if cmd == C.SET_CONFIG:
                assert len(body) == 54, len(body)
                name, _lat, _lon, _cap, self.pairing, self.button, self.led = struct.unpack_from("<32sffBBBB", body)
                assert name.startswith(b"Haustuer")
                assert struct.unpack_from("<H", body, 52)[0] == 37  # time zone id kept
                return ok
            if cmd == C.SET_ADVANCED_CONFIG:
                assert len(body) == 26, len(body)
                vals = struct.unpack("<HBHHBHBBBBHBBBBBBBBBB", body)
                self.strike_duration, self.rto_timeout, self.single_press = vals[5], vals[7], vals[17]
                return ok
            if cmd == C.UPDATE_TIME:
                self.time_set = struct.unpack("<HBBBBB", body)
                return ok
            if cmd == C.REQUEST_LOG_ENTRIES:
                _start, count, order, _total = struct.unpack("<IHBB", body)
                assert order == 1
                frames: list[bytes] = []
                for entry in self.logs[:count]:
                    frames += out(C.LOG_ENTRY, entry)
                return frames + ok
            return ok
        raise AssertionError(hex(cmd))


class FakeConnection:
    """Stands in for protocol._Connection, wired to a FakeOpener."""

    opener: FakeOpener

    def __init__(self, device, device_callback, char_uuid, key) -> None:
        self.key = key

    async def __aenter__(self):
        session = p._Session(None, "x", self.key)
        handler = self.opener.encrypted if self.key is not None else self.opener.unencrypted

        async def write(data: bytes) -> None:
            for frame in handler(data):
                session._on_data(None, bytearray(frame))

        session.write = write
        return session

    async def __aexit__(self, *exc) -> None:
        return None
