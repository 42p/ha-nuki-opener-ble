"""Binary structures exchanged with the Nuki Opener (all little endian, packed)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
import struct
from typing import Any

from .const import (
    DOORBELL_SOURCES,
    LoggingType,
    OpenerLockState,
    OpenerMode,
)


class ParseError(ValueError):
    """Payload too short or malformed."""


def _utc(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        return None


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _need(payload: bytes, size: int, what: str) -> None:
    if len(payload) < size:
        raise ParseError(f"{what}: {len(payload)} bytes, need {size}")


# --- keyturner states ----------------------------------------------------------

_STATE = struct.Struct("<BBBHBBBBBhBBBBBB")  # up to last action completion status


@dataclass(slots=True)
class OpenerState:
    mode: int
    lock_state: int
    trigger: int
    device_time: datetime | None
    timezone_offset: int
    critical_battery_state: int
    config_update_count: int
    ring_to_open_timer: int
    last_action: int
    last_action_trigger: int
    last_action_completion: int
    accessory_battery_state: int | None

    @property
    def ring_to_open(self) -> bool:
        return self.lock_state == OpenerLockState.RTO_ACTIVE

    @property
    def continuous_mode(self) -> bool:
        return self.mode == OpenerMode.CONTINUOUS

    @property
    def battery_critical(self) -> bool:
        return bool(self.critical_battery_state & 0x01)

    @property
    def keypad_battery_critical(self) -> bool | None:
        acc = self.accessory_battery_state
        if acc is None or acc == 0xFF or not acc & 0x01:
            return None
        return (acc & 0x03) == 0x03

    @classmethod
    def parse(cls, payload: bytes) -> OpenerState:
        _need(payload, _STATE.size, "keyturner states")
        (mode, lock, trig, y, mo, d, h, mi, s, tz, batt, cuc, rto, act, act_trig, compl) = (
            _STATE.unpack_from(payload)
        )
        # unused1 (2) + unused2..6 (5) follow, then the accessory battery state
        acc = payload[_STATE.size + 7] if len(payload) > _STATE.size + 7 else None
        return cls(
            mode=mode,
            lock_state=lock,
            trigger=trig,
            device_time=_utc(y, mo, d, h, mi, s),
            timezone_offset=tz,
            critical_battery_state=batt,
            config_update_count=cuc,
            ring_to_open_timer=rto,
            last_action=act,
            last_action_trigger=act_trig,
            last_action_completion=compl,
            accessory_battery_state=acc,
        )


# --- battery report ------------------------------------------------------------

_BATTERY = struct.Struct("<HHBB")


@dataclass(slots=True)
class BatteryReport:
    drain_mws: int
    voltage: float  # V
    critical_battery_state: int

    @classmethod
    def parse(cls, payload: bytes) -> BatteryReport:
        _need(payload, _BATTERY.size, "battery report")
        drain, mv, crit, _action = _BATTERY.unpack_from(payload)
        return cls(drain_mws=drain, voltage=mv / 1000, critical_battery_state=crit)


# --- configuration -------------------------------------------------------------

# nukiId, name, lat, lon, capabilities, pairing, button, led, time(7), tz offset,
# dst, hasFob, fob1-3, operating mode, advertising mode, hasKeypad, fw[3], hw[2]
_CONFIG = struct.Struct("<I32sffBBBBHBBBBBhBBBBBBBB3s2s")
_CONFIG_TZ_ID = struct.Struct("<H")
_NEW_CONFIG = struct.Struct("<32sffBBBBhBBBBBBH")


@dataclass(slots=True)
class OpenerConfig:
    nuki_id: int
    name: str
    latitude: float
    longitude: float
    capabilities: int
    pairing_enabled: bool
    button_enabled: bool
    led_flash_enabled: bool
    device_time: datetime | None
    timezone_offset: int
    dst_mode: int
    has_fob: bool
    fob_action_1: int
    fob_action_2: int
    fob_action_3: int
    operating_mode: int
    advertising_mode: int
    has_keypad: bool
    firmware_version: str
    hardware_revision: str
    timezone_id: int | None
    raw_name: bytes = field(repr=False, default=b"")

    @classmethod
    def parse(cls, payload: bytes) -> OpenerConfig:
        _need(payload, _CONFIG.size, "config")
        (nid, name, lat, lon, cap, pair, btn, led, y, mo, d, h, mi, s, tz, dst, has_fob,
         f1, f2, f3, op, adv, has_kp, fw, hw) = _CONFIG.unpack_from(payload)
        off = _CONFIG.size
        tz_id = (
            _CONFIG_TZ_ID.unpack_from(payload, off)[0]
            if len(payload) >= off + _CONFIG_TZ_ID.size
            else None
        )
        has_kp_v2 = payload[off + 2] if len(payload) > off + 2 else 0xFF
        return cls(
            nuki_id=nid,
            name=_cstr(name),
            latitude=lat,
            longitude=lon,
            capabilities=cap,
            pairing_enabled=bool(pair),
            button_enabled=bool(btn),
            led_flash_enabled=bool(led),
            device_time=_utc(y, mo, d, h, mi, s),
            timezone_offset=tz,
            dst_mode=dst,
            has_fob=bool(has_fob),
            fob_action_1=f1,
            fob_action_2=f2,
            fob_action_3=f3,
            operating_mode=op,
            advertising_mode=adv,
            has_keypad=bool(has_kp) or has_kp_v2 not in (0, 0xFF),
            firmware_version=".".join(str(b) for b in fw),
            hardware_revision=".".join(str(b) for b in hw),
            timezone_id=tz_id,
            raw_name=name,
        )

    def build_set_payload(self, **changes: Any) -> bytes:
        """Return a SET_CONFIG payload with the given fields changed."""
        if self.timezone_id is None:
            raise ParseError("Config without time zone ID cannot be written back safely")
        new = replace(self, **changes)
        name = new.name.encode()[:32].ljust(32, b"\x00") if "name" in changes else new.raw_name
        return _NEW_CONFIG.pack(
            name, new.latitude, new.longitude, new.capabilities,
            int(new.pairing_enabled), int(new.button_enabled), int(new.led_flash_enabled),
            new.timezone_offset, new.dst_mode, new.fob_action_1, new.fob_action_2,
            new.fob_action_3, new.operating_mode, new.advertising_mode, new.timezone_id,
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw_name")
        return data


_ADV = struct.Struct("<HBHHBHBBBBHBBBBBBBB")  # through double button press action
_ADV_TAIL = struct.Struct("<BB")  # battery type, automatic battery type detection


@dataclass(slots=True)
class OpenerAdvancedConfig:
    intercom_id: int
    bus_mode_switch: int
    short_circuit_duration: int
    electric_strike_delay: int  # ms
    random_electric_strike_delay: bool
    electric_strike_duration: int  # ms
    disable_rto_after_ring: bool
    rto_timeout: int  # minutes
    unknown: int
    doorbell_suppression: int
    doorbell_suppression_duration: int  # ms
    sound_ring: int
    sound_open: int
    sound_rto: int
    sound_cm: int
    sound_confirmation: int
    sound_level: int
    single_button_press_action: int
    double_button_press_action: int
    battery_type: int | None
    automatic_battery_type_detection: bool | None
    auto_update_enabled: bool | None

    @classmethod
    def parse(cls, payload: bytes) -> OpenerAdvancedConfig:
        _need(payload, _ADV.size - 2, "advanced config")  # up to sound level is mandatory
        padded = payload.ljust(_ADV.size, b"\xff")
        values = list(_ADV.unpack_from(padded))
        tail: list[int | None] = [None, None, None]
        if len(payload) >= _ADV.size + _ADV_TAIL.size:
            tail[0], tail[1] = _ADV_TAIL.unpack_from(payload, _ADV.size)
        if len(payload) > _ADV.size + _ADV_TAIL.size:
            tail[2] = payload[_ADV.size + _ADV_TAIL.size]
        values[4] = bool(values[4])
        values[6] = bool(values[6])
        return cls(
            *values,
            battery_type=tail[0],
            automatic_battery_type_detection=None if tail[1] is None else bool(tail[1]),
            auto_update_enabled=None if tail[2] in (None, 0xFF) else bool(tail[2]),
        )

    @property
    def writable(self) -> bool:
        return self.battery_type is not None

    def build_set_payload(self, **changes: Any) -> bytes:
        """Return a SET_ADVANCED_CONFIG payload with the given fields changed."""
        if not self.writable:
            raise ParseError("Advanced config is incomplete and cannot be written back safely")
        n = replace(self, **changes)
        return _ADV.pack(
            n.intercom_id, n.bus_mode_switch, n.short_circuit_duration,
            n.electric_strike_delay, int(n.random_electric_strike_delay),
            n.electric_strike_duration, int(n.disable_rto_after_ring), n.rto_timeout,
            n.unknown, n.doorbell_suppression, n.doorbell_suppression_duration,
            n.sound_ring, n.sound_open, n.sound_rto, n.sound_cm, n.sound_confirmation,
            n.sound_level, n.single_button_press_action, n.double_button_press_action,
        ) + _ADV_TAIL.pack(n.battery_type, int(bool(n.automatic_battery_type_detection)))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- log entries ---------------------------------------------------------------

_LOG = struct.Struct("<IHBBBBBI32sB")


@dataclass(slots=True)
class LogEntry:
    index: int
    timestamp: datetime | None
    auth_id: int
    name: str
    type: int
    data: bytes

    @classmethod
    def parse(cls, payload: bytes) -> LogEntry:
        _need(payload, _LOG.size, "log entry")
        idx, y, mo, d, h, mi, s, auth, name, typ = _LOG.unpack_from(payload)
        return cls(
            index=idx,
            timestamp=_utc(y, mo, d, h, mi, s),
            auth_id=auth,
            name=_cstr(name),
            type=typ,
            data=payload[_LOG.size : _LOG.size + 8].ljust(8, b"\x00"),
        )

    @property
    def is_ring(self) -> bool:
        return self.type == LoggingType.DOORBELL_RECOGNITION

    @property
    def ring_opened(self) -> bool:
        """Doorbell ring that opened the door (RTO or continuous mode was active)."""
        return self.is_ring and (self.data[0] & 0x03) != 0

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "index": self.index,
            "time": self.timestamp.isoformat() if self.timestamp else None,
            "auth_id": self.auth_id,
            "name": self.name,
            "type": _enum_name(LoggingType, self.type),
        }
        d = self.data
        if self.type == LoggingType.LOCK_ACTION:
            info |= {"action": d[0], "trigger": d[1], "completion_status": d[3]}
        elif self.type == LoggingType.KEYPAD_ACTION:
            info |= {
                "action": d[0],
                "source": {0: "arrow_key", 1: "code", 2: "fingerprint"}.get(d[1], d[1]),
                "completion_status": d[2],
                "code_id": d[3] | d[4] << 8,
            }
        elif self.type == LoggingType.DOORBELL_RECOGNITION:
            info |= {
                "mode": {0: "none", 1: "rto", 2: "cm"}.get(d[0] & 3, "unknown"),
                "source": DOORBELL_SOURCES.get(d[1], d[1]),
                "geofence": d[2] == 1,
                "doorbell_suppression": d[3] == 1,
                "sound_id": d[4],
                "completion_status": d[5],
                "code_id": d[6] | d[7] << 8,
            }
        return info


def _enum_name(enum_cls, value: int) -> str:
    try:
        return enum_cls(value).name.lower()
    except ValueError:
        return f"0x{value:02x}"
