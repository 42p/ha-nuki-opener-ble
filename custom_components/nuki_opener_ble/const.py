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

DEFAULT_CLIENT_NAME = "Home Assistant"
UPDATE_INTERVAL = timedelta(minutes=10)

# --- BLE UUIDs (Nuki Opener) -------------------------------------------------
PAIRING_SERVICE_UUID = "a92ae100-5501-11e4-916c-0800200c9a66"
PAIRING_GDIO_UUID = "a92ae101-5501-11e4-916c-0800200c9a66"
KEYTURNER_SERVICE_UUID = "a92ae200-5501-11e4-916c-0800200c9a66"
KEYTURNER_GDIO_UUID = "a92ae201-5501-11e4-916c-0800200c9a66"
KEYTURNER_USDIO_UUID = "a92ae202-5501-11e4-916c-0800200c9a66"

# The Opener advertises an iBeacon whose proximity UUID equals the keyturner service.
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
    ERROR_REPORT = 0x0012
    AUTHORIZATION_ID_CONFIRMATION = 0x001E


class Status(IntEnum):
    """Payload of the STATUS command."""

    COMPLETE = 0x00
    ACCEPTED = 0x01


class ClientType(IntEnum):
    """ID type used during pairing."""

    APP = 0x00
    BRIDGE = 0x01


class OpenerAction(IntEnum):
    """Lock actions supported by the Opener."""

    ACTIVATE_RTO = 0x01
    DEACTIVATE_RTO = 0x02
    ELECTRIC_STRIKE_ACTUATION = 0x03
    ACTIVATE_CONTINUOUS_MODE = 0x04
    DEACTIVATE_CONTINUOUS_MODE = 0x05


class OpenerMode(IntEnum):
    """`Nuki state` field of the Opener keyturner states."""

    UNINITIALIZED = 0x00
    PAIRING = 0x01
    DOOR = 0x02
    CONTINUOUS = 0x03
    MAINTENANCE = 0x04


class OpenerLockState(IntEnum):
    """`Lock state` field of the Opener keyturner states."""

    LOCKED = 0x00
    RTO_ACTIVE = 0x01
    OPEN = 0x03
    OPENING = 0x05
    UNDEFINED = 0x07


# Payload length of unencrypted responses, used to reassemble fragmented indications.
UNENCRYPTED_PAYLOAD_LENGTHS: dict[int, int] = {
    Command.PUBLIC_KEY: 32,
    Command.CHALLENGE: 32,
    Command.AUTHORIZATION_ID: 32 + 4 + 16 + 32,
    Command.STATUS: 1,
    Command.ERROR_REPORT: 3,
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
    0x40: "too many PIN attempts",
    0xFD: "bad CRC",
    0xFE: "bad length",
    0xFF: "unknown error",
}
