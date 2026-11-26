"""Data coordinator for the Nuki Opener BLE integration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    APPLE_MANUFACTURER_ID,
    CONF_APP_ID,
    CONF_AUTH_ID,
    CONF_INFO_INTERVAL,
    CONF_PIN,
    CONF_POLL_INTERVAL,
    CONF_SHARED_KEY,
    DEFAULT_INFO_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    ERROR_BAD_PIN,
    ERROR_INVALID_AUTH_ID,
    FOLLOW_UP_DELAY,
    IBEACON_PREFIX,
    LOG_EVENT,
    LOG_FETCH_COUNT,
    RING_EVENT,
    OpenerAction,
    OpenerLockState,
    OpenerMode,
    Trigger,
)
from .models import (
    BatteryReport,
    LogEntry,
    OpenerAdvancedConfig,
    OpenerConfig,
    OpenerState,
    ParseError,
)
from .protocol import NukiDeviceError, NukiError, NukiOpenerClient, OpenerSession

_LOGGER = logging.getLogger(__name__)

type NukiOpenerConfigEntry = ConfigEntry[NukiOpenerCoordinator]
type RingListener = Callable[[str, dict[str, Any]], None]

RSSI_PUSH_INTERVAL = 60.0
OPENING_FOLLOW_UP_WINDOW = 15.0
IGNORE_BEACON_AFTER_COMMAND = 15.0


@dataclass(slots=True)
class OpenerData:
    state: OpenerState
    battery: BatteryReport | None = None
    config: OpenerConfig | None = None
    advanced: OpenerAdvancedConfig | None = None
    last_log: LogEntry | None = None
    last_ring: datetime | None = None
    rssi: int | None = None
    info_updated: float = field(default=0.0)


class NukiOpenerCoordinator(DataUpdateCoordinator[OpenerData]):
    """Talks to the Opener; refreshes on beacon signal, on a timer and after actions."""

    config_entry: NukiOpenerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NukiOpenerConfigEntry) -> None:
        options = entry.options
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_ADDRESS]}",
            update_interval=timedelta(
                seconds=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self.address: str = entry.data[CONF_ADDRESS]
        pin = options.get(CONF_PIN)
        self.client = NukiOpenerClient(
            auth_id=entry.data[CONF_AUTH_ID],
            shared_key=bytes.fromhex(entry.data[CONF_SHARED_KEY]),
            app_id=entry.data[CONF_APP_ID],
            pin=int(pin) if pin not in (None, "") else None,
        )
        self._info_interval = float(options.get(CONF_INFO_INTERVAL, DEFAULT_INFO_INTERVAL))
        self.ble_lock = asyncio.Lock()
        self._beacon_flag = False
        self._last_log_index: int | None = None
        self._rssi_pushed = 0.0
        self._opening_since: float | None = None
        self._follow_up: CALLBACK_TYPE | None = None
        self._ring_listeners: list[RingListener] = []
        self._ignore_beacon_until = 0.0

    # --- helpers -------------------------------------------------------------

    @property
    def has_pin(self) -> bool:
        return self.client.pin is not None

    @property
    def _issue_id(self) -> str:
        return f"bad_pin_{self.config_entry.entry_id}"

    def _ble_device(self) -> tuple[BLEDevice, Callable[[], BLEDevice]]:
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise NukiError(
                f"Opener {self.address} is not reachable by any connectable "
                "Bluetooth adapter"
            )

        def _latest() -> BLEDevice:
            return (
                bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )
                or device
            )

        return device, _latest

    async def _run[T](self, job: Callable[[OpenerSession], Awaitable[T]]) -> T:
        async with self.ble_lock:
            device, latest = self._ble_device()
            try:
                return await self.client.run(device, latest, job)
            except NukiDeviceError as err:
                self._handle_device_error(err)
                raise

    def _handle_device_error(self, err: NukiDeviceError) -> None:
        if err.code == ERROR_INVALID_AUTH_ID:
            raise ConfigEntryAuthFailed(str(err)) from err
        if err.code == ERROR_BAD_PIN and self.client.pin is not None:
            # Stop using the PIN so repeated attempts cannot lock the device.
            self.client.pin = None
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="bad_pin",
                translation_placeholders={"name": self.config_entry.title},
            )

    @callback
    def async_add_ring_listener(self, listener: RingListener) -> CALLBACK_TYPE:
        self._ring_listeners.append(listener)
        return lambda: self._ring_listeners.remove(listener)

    def _fire_ring(self, opened: bool, details: dict[str, Any]) -> None:
        event_type = "ring_opened" if opened else "ring"
        _LOGGER.debug("%s: doorbell %s %s", self.address, event_type, details)
        self.hass.bus.async_fire(
            RING_EVENT,
            {"device_address": self.address, **details, "type": event_type},
        )
        for listener in list(self._ring_listeners):
            listener(event_type, details)

    # --- polling -------------------------------------------------------------

    async def _async_update_data(self) -> OpenerData:
        beacon_flag, self._beacon_flag = self._beacon_flag, False
        previous = self.data
        info_due = previous is None or (
            time.monotonic() - previous.info_updated >= self._info_interval
        )
        use_pin = self.client.pin is not None

        async def job(s: OpenerSession) -> tuple[OpenerData, list[LogEntry] | None]:
            data = (
                replace(previous, state=await s.state())
                if previous
                else OpenerData(state=await s.state())
            )
            if info_due:
                try:
                    data.battery = await s.battery_report()
                    data.config = await s.config()
                    data.advanced = await s.advanced_config()
                    data.info_updated = time.monotonic()
                except (NukiError, ParseError) as err:
                    _LOGGER.debug("Could not read Opener info: %s", err)
            logs: list[LogEntry] | None = None  # None = log not read this time
            if use_pin and data.state.lock_state not in (
                OpenerLockState.OPEN,
                OpenerLockState.OPENING,
            ):
                logs = await s.log_entries(LOG_FETCH_COUNT)
            return data, logs

        try:
            data, logs = await self._run(job)
        except (NukiError, ParseError) as err:
            raise UpdateFailed(str(err)) from err

        if use_pin and self.client.pin is not None:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

        if previous is not None:
            data.rssi = previous.rssi
        if logs is not None:
            self._process_logs(data, logs)
        elif not use_pin and previous is not None:
            self._detect_ring_without_log(previous.state, data.state, beacon_flag, data)

        self._schedule_follow_up(data.state)
        return data

    def _process_logs(self, data: OpenerData, logs: list[LogEntry]) -> None:
        logs.sort(key=lambda e: e.index)
        newest = logs[-1].index if logs else 0
        if logs:
            data.last_log = logs[-1]
        if self._last_log_index is None:
            self._last_log_index = newest  # baseline, do not replay history
            return
        for entry in logs:
            if entry.index <= self._last_log_index:
                continue
            info = entry.describe()
            self.hass.bus.async_fire(LOG_EVENT, {"device_address": self.address, **info})
            if entry.is_ring:
                data.last_ring = entry.timestamp or dt_util.utcnow()
                self._fire_ring(entry.ring_opened, info)
        self._last_log_index = max(self._last_log_index, newest)

    def _detect_ring_without_log(
        self, prev: OpenerState, cur: OpenerState, beacon_flag: bool, data: OpenerData
    ) -> None:
        """Same heuristics as Nuki Hub when no PIN is available."""
        if not beacon_flag:
            return
        opening = (OpenerLockState.OPEN, OpenerLockState.OPENING)
        opened: bool | None = None
        if (
            cur.mode == OpenerMode.CONTINUOUS
            and cur.trigger == Trigger.MANUAL
            and cur.lock_state in opening
            and prev.lock_state not in opening
        ):
            opened = True
        elif (
            cur.trigger == Trigger.MANUAL
            and cur.lock_state in opening
            and prev.lock_state == OpenerLockState.RTO_ACTIVE
        ):
            opened = True
        elif (
            cur.lock_state == OpenerLockState.LOCKED
            and prev.lock_state == OpenerLockState.LOCKED
            and prev.mode == cur.mode
        ):
            opened = False
        if opened is not None:
            data.last_ring = dt_util.utcnow()
            self._fire_ring(opened, {"source": "doorbell"})

    def _schedule_follow_up(self, state: OpenerState) -> None:
        if state.lock_state not in (OpenerLockState.OPEN, OpenerLockState.OPENING):
            self._opening_since = None
            return
        now = time.monotonic()
        self._opening_since = self._opening_since or now
        if now - self._opening_since > OPENING_FOLLOW_UP_WINDOW or self._follow_up:
            return

        @callback
        def _refresh(_now: datetime) -> None:
            self._follow_up = None
            self.hass.async_create_task(self.async_request_refresh())

        self._follow_up = async_call_later(self.hass, FOLLOW_UP_DELAY, _refresh)

    async def async_shutdown(self) -> None:
        if self._follow_up:
            self._follow_up()
            self._follow_up = None
        await super().async_shutdown()

    # --- commands ------------------------------------------------------------

    async def _command(self, job: Callable[[OpenerSession], Awaitable[Any]]) -> None:
        """Run a command job that returns a dict of OpenerData fields to update."""
        try:
            changes = await self._run(job)
        except ConfigEntryAuthFailed:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError("Nuki Opener: pairing is no longer valid")
        except (NukiError, ParseError) as err:
            raise HomeAssistantError(f"Nuki Opener: {err}") from err
        finally:
            # The beacon keeps flagging our own change for a while: not a doorbell ring.
            self._ignore_beacon_until = time.monotonic() + IGNORE_BEACON_AFTER_COMMAND
        if self.data is not None:
            data = replace(self.data, **changes)
            self.async_set_updated_data(data)
            self._schedule_follow_up(data.state)

    async def async_action(self, action: OpenerAction) -> None:
        async def job(s: OpenerSession) -> dict[str, Any]:
            await s.lock_action(action)
            return {"state": await s.state()}

        await self._command(job)

    async def async_set_config(self, **changes: Any) -> None:
        async def job(s: OpenerSession) -> dict[str, Any]:
            current = await s.config()
            await s.set_config(current.build_set_payload(**changes))
            return {"config": await s.config(), "state": await s.state()}

        await self._command(job)

    async def async_set_advanced_config(self, **changes: Any) -> None:
        async def job(s: OpenerSession) -> dict[str, Any]:
            current = await s.advanced_config()
            await s.set_advanced_config(current.build_set_payload(**changes))
            return {"advanced": await s.advanced_config(), "state": await s.state()}

        await self._command(job)

    async def async_sync_time(self) -> None:
        async def job(s: OpenerSession) -> dict[str, Any]:
            await s.update_time()
            return {"state": await s.state()}

        await self._command(job)

    async def async_reboot(self) -> None:
        async def job(s: OpenerSession) -> dict[str, Any]:
            await s.reboot()
            return {}

        await self._command(job)

    async def async_refresh_info(self) -> None:
        if self.data is not None:
            self.data.info_updated = 0.0
        await self.async_refresh()

    # --- advertisements ------------------------------------------------------

    @callback
    def async_handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        """Track RSSI and refresh when the beacon flags a pending state change."""
        if self.data is not None and service_info.rssi is not None:
            self.data.rssi = service_info.rssi
            now = time.monotonic()
            if now - self._rssi_pushed >= RSSI_PUSH_INTERVAL:
                self._rssi_pushed = now
                self.async_update_listeners()

        data = service_info.manufacturer_data.get(APPLE_MANUFACTURER_ID)
        if not data or len(data) < 23 or data[:2] != IBEACON_PREFIX:
            return
        if (
            data[22] & 0x01
            and not self.ble_lock.locked()
            and time.monotonic() >= self._ignore_beacon_until
        ):
            _LOGGER.debug("%s signalled a state change", self.address)
            self._beacon_flag = True
            self.hass.async_create_task(self.async_request_refresh())
