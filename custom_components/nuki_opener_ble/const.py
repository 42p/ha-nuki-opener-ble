"""Constants for the Nuki Opener BLE integration."""

from __future__ import annotations

from datetime import timedelta
from enum import IntEnum
from uuid import UUID

DOMAIN = "nuki_opener_ble"

CONF_AUTH_ID = "auth_id"
CONF_SHARED_KEY = "shared_key"
CONF_APP_ID = "app_id"
CONF_CLIENT_NAME = "client_name"
CONF_PAIR_AS_BRIDGE = "pair_as_bridge"
CONF_PIN = "pin"
CONF_POLL_INTERVAL = "poll_interval"
CONF_INFO_INTERVAL = "info_interval"

DEFAULT_CLIENT_NAME = "Home Assistant"
DEFAULT_POLL_INTERVAL = 600  # seconds, state poll when no beacon signal arrives
DEFAULT_INFO_INTERVAL = 3600  # seconds, battery report + configuration refresh
FOLLOW_UP_DELAY = timedelta(seconds=4)  # re-read while the strike is opening
RING_EVENT = f"{DOMAIN}_ring"
LOG_EVENT = f"{DOMAIN}_log"
LOG_FETCH_COUNT = 5

# --- BLE UUIDs (Nuki Opener) -------------------------------------------------
PAIRING_SERVICE_UUID = "a92ae100-5501-11e4-916c-0800200c9a66"
PAIRING_GDIO_UUID = "a92ae101-5501-11e4-916c-0800200c9a66"
KEYTURNER_SERVICE_UUID = "a92ae200-5501-11e4-916c-0800200c9a66"
KEYTURNER_GDIO_UUID = "a92ae201-5501-11e4-916c-0800200c9a66"
KEYTURNER_USDIO_UUID = "a92ae202-5501-11e4-916c-0800200c9a66"

# The Opener advertises an iBeacon whose proximity UUID equals the keyturner service;
# bit 0 of the measured-power byte is set while a state change is pending.
APPLE_MANUFACTURER_ID = 0x004C
IBEACON_PREFIX = bytes([0x02, 0x15])
OPENER_BEACON_UUID = UUID(KEYTURNER_SERVICE_UUID).bytes


class Command(IntEnum):
    """Nuki BLE command identifiers."""

    REQUEST_DATA = 0x0001
    PUBLIC_KEY = 0x0003
    CHALLENGE = 0x0004
    AUTHORIZATION_AUTHENTICATOR = 0x0005
    AUTHORIZATION_DATA = 0x0006
    AUTHORIZATION_ID = 0x0007
    KEYTURNER_STATES = 0x000C
    LOCK_ACTION = 0x000D
    STATUS = 0x000E
    BATTERY_REPORT = 0x0011
    ERROR_REPORT = 0x0012
    SET_CONFIG = 0x0013
    REQUEST_CONFIG = 0x0014
    CONFIG = 0x0015
    REQUEST_REBOOT = 0x001D
    AUTHORIZATION_ID_CONFIRMATION = 0x001E
    VERIFY_SECURITY_PIN = 0x0020
    UPDATE_TIME = 0x0021
    REQUEST_LOG_ENTRIES = 0x0031
    LOG_ENTRY = 0x0032
    LOG_ENTRY_COUNT = 0x0033
    SET_ADVANCED_CONFIG = 0x0035
    REQUEST_ADVANCED_CONFIG = 0x0036
    ADVANCED_CONFIG = 0x0037
    CONTINUOUS_MODE_ACTION = 0x0057


class Status(IntEnum):
    COMPLETE = 0x00
    ACCEPTED = 0x01


class ClientType(IntEnum):
    APP = 0x00
    BRIDGE = 0x01


class OpenerAction(IntEnum):
    ACTIVATE_RTO = 0x01
    DEACTIVATE_RTO = 0x02
    ELECTRIC_STRIKE_ACTUATION = 0x03
    ACTIVATE_CM = 0x04
    DEACTIVATE_CM = 0x05
    FOB_ACTION_1 = 0x81
    FOB_ACTION_2 = 0x82
    FOB_ACTION_3 = 0x83


class OpenerMode(IntEnum):
    """`Nuki state` field of the keyturner states."""

    UNINITIALIZED = 0x00
    PAIRING = 0x01
    DOOR = 0x02
    CONTINUOUS = 0x03
    MAINTENANCE = 0x04


class OpenerLockState(IntEnum):
    """`Lock state` field of the Opener keyturner states."""

    UNCALIBRATED = 0x00
    LOCKED = 0x01
    RTO_ACTIVE = 0x03
    OPEN = 0x05
    OPENING = 0x07
    UNDEFINED = 0xFF


class Trigger(IntEnum):
    SYSTEM = 0x00
    MANUAL = 0x01
    BUTTON = 0x02
    AUTOMATIC = 0x03
    UNDEFINED = 0xFF


class CompletionStatus(IntEnum):
    SUCCESS = 0x00
    CANCELED = 0x02
    TOO_RECENT = 0x03
    BUSY = 0x04
    INCOMPLETE = 0x08
    NOT_AUTHORIZED = 0x09
    INVALID_CODE = 0xE0
    OTHER_ERROR = 0xFE
    UNKNOWN = 0xFF


class ButtonPressAction(IntEnum):
    NO_ACTION = 0x00
    TOGGLE_RTO = 0x01
    ACTIVATE_RTO = 0x02
    DEACTIVATE_RTO = 0x03
    TOGGLE_CM = 0x04
    ACTIVATE_CM = 0x05
    DEACTIVATE_CM = 0x06
    OPEN = 0x07


class BatteryType(IntEnum):
    ALKALI = 0x00
    ACCUMULATORS = 0x01
    LITHIUM = 0x02


class AdvertisingMode(IntEnum):
    AUTOMATIC = 0x00
    NORMAL = 0x01
    SLOW = 0x02
    SLOWEST = 0x03


class LoggingType(IntEnum):
    LOGGING_ENABLED = 0x01
    LOCK_ACTION = 0x02
    CALIBRATION = 0x03
    KEYPAD_ACTION = 0x05
    DOORBELL_RECOGNITION = 0x06


DOORBELL_SOURCES = {
    0: "doorbell",
    1: "time_control",
    2: "app",
    3: "button",
    4: "fob",
    5: "bridge",
    6: "keypad",
}

ERROR_CODES: dict[int, str] = {
    0x10: "not in pairing mode (hold the Opener button for 5 s)",
    0x11: "bad authenticator",
    0x12: "bad parameter",
    0x13: "maximum number of users reached",
    0x20: "not authorized",
    0x21: "bad PIN",
    0x22: "bad nonce",
    0x23: "bad parameter",
    0x24: "invalid authorization ID (pairing was removed on the device)",
    0x25: "authorization disabled",
    0x26: "remote access not allowed",
    0x27: "action not allowed at this time",
    0x28: "too many PIN attempts",
    0x29: "too many entries",
    0x45: "device busy",
    0x4C: "battery voltage too low",
    0x4D: "firmware update needed",
    0xFD: "bad CRC",
    0xFE: "bad length",
    0xFF: "unknown error",
}
ERROR_BAD_PIN = 0x21
ERROR_INVALID_AUTH_ID = 0x24
ERROR_NOT_PAIRING = 0x10
ERROR_BUSY = 0x45
