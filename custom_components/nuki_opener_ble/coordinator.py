"""Data coordinator for the Nuki Opener BLE integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    APPLE_MANUFACTURER_ID,
    CONF_APP_ID,
    CONF_AUTH_ID,
    CONF_SHARED_KEY,
    DOMAIN,
    IBEACON_PREFIX,
    UPDATE_INTERVAL,
    OpenerAction,
)
from .protocol import NukiError, NukiOpenerClient, OpenerState

_LOGGER = logging.getLogger(__name__)

type NukiOpenerConfigEntry = ConfigEntry[NukiOpenerCoordinator]


class NukiOpenerCoordinator(DataUpdateCoordinator[OpenerState]):
    """Polls the Opener and refreshes when its beacon signals a state change."""

    config_entry: NukiOpenerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NukiOpenerConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_ADDRESS]}",
            update_interval=UPDATE_INTERVAL,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self.client = NukiOpenerClient(
            auth_id=entry.data[CONF_AUTH_ID],
            shared_key=bytes.fromhex(entry.data[CONF_SHARED_KEY]),
            app_id=entry.data[CONF_APP_ID],
        )
        # The Opener accepts only one connection at a time.
        self._ble_lock = asyncio.Lock()

    def _ble_device(self) -> tuple[BLEDevice, Callable[[], BLEDevice]]:
        """Return the current BLEDevice and a callback yielding the freshest one."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise NukiError(
                f"Opener {self.address} is not reachable by any connectable "
                "Bluetooth adapter or proxy"
            )

        def _latest() -> BLEDevice:
            return (
                bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )
                or device
            )

        return device, _latest

    async def _async_update_data(self) -> OpenerState:
        try:
            async with self._ble_lock:
                return await self.client.get_state(*self._ble_device())
        except NukiError as err:
            raise UpdateFailed(str(err)) from err

    async def async_action(self, action: OpenerAction) -> None:
        """Run a lock action and publish the resulting state."""
        try:
            async with self._ble_lock:
                device, latest = self._ble_device()
                state = await self.client.lock_action(device, action, latest)
        except NukiError as err:
            raise HomeAssistantError(f"Nuki Opener: {err}") from err
        self.async_set_updated_data(state)

    @callback
    def async_handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        """Refresh when the iBeacon TX-power LSB flags a pending state change."""
        data = service_info.manufacturer_data.get(APPLE_MANUFACTURER_ID)
        if not data or len(data) < 23 or data[:2] != IBEACON_PREFIX:
            return
        if data[22] & 0x01 and not self._ble_lock.locked():
            _LOGGER.debug("%s signalled a state change", self.address)
            self.hass.async_create_task(self.async_request_refresh())
