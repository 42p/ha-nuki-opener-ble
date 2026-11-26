"""Config flow: discover the Opener over Bluetooth and pair with it."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import (
    APPLE_MANUFACTURER_ID,
    CONF_APP_ID,
    CONF_AUTH_ID,
    CONF_CLIENT_NAME,
    CONF_PAIR_AS_BRIDGE,
    CONF_SHARED_KEY,
    DEFAULT_CLIENT_NAME,
    DOMAIN,
    IBEACON_PREFIX,
    KEYTURNER_SERVICE_UUID,
    OPENER_BEACON_UUID,
    PAIRING_SERVICE_UUID,
    ClientType,
)
from .protocol import NukiDeviceError, NukiError, async_pair

_LOGGER = logging.getLogger(__name__)


def is_opener(info: BluetoothServiceInfoBleak) -> bool:
    """Return True if the advertisement belongs to a Nuki Opener."""
    uuids = {u.lower() for u in info.service_uuids}
    if {PAIRING_SERVICE_UUID, KEYTURNER_SERVICE_UUID} & uuids:
        return True
    data = info.manufacturer_data.get(APPLE_MANUFACTURER_ID, b"")
    return data[:2] == IBEACON_PREFIX and data[2:18] == OPENER_BEACON_UUID


def _title(info: BluetoothServiceInfoBleak) -> str:
    name = info.name or ""
    return name if name and name != info.address else f"Nuki Opener {info.address[-5:]}"


class NukiOpenerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nuki Opener BLE."""

    VERSION = 1

    def __init__(self) -> None:
        self._info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not is_opener(discovery_info):
            return self.async_abort(reason="not_supported")
        self._info = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_pair()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._info = self._discovered[address]
            return await self.async_step_pair()

        configured = self._async_current_ids(include_ignore=False)
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if info.address not in configured and is_opener(info):
                self._discovered[info.address] = info
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{_title(info)} ({addr})"
                            for addr, info in self._discovered.items()
                        }
                    )
                }
            ),
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._info is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            device = (
                bluetooth.async_ble_device_from_address(
                    self.hass, self._info.address, connectable=True
                )
                or self._info.device
            )
            client_type = (
                ClientType.BRIDGE if user_input[CONF_PAIR_AS_BRIDGE] else ClientType.APP
            )
            try:
                result = await async_pair(
                    device, user_input[CONF_CLIENT_NAME], client_type
                )
            except NukiDeviceError as err:
                _LOGGER.warning("Pairing rejected: %s", err)
                errors["base"] = "not_pairing_mode" if err.code == 0x10 else "pairing_failed"
            except NukiError as err:
                _LOGGER.warning("Pairing failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=_title(self._info),
                    data={
                        CONF_ADDRESS: self._info.address,
                        CONF_AUTH_ID: result.auth_id,
                        CONF_SHARED_KEY: result.shared_key.hex(),
                        CONF_APP_ID: result.app_id,
                    },
                )

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_NAME, default=DEFAULT_CLIENT_NAME): str,
                    vol.Required(CONF_PAIR_AS_BRIDGE, default=False): bool,
                }
            ),
            description_placeholders={"name": _title(self._info)},
            errors=errors,
        )
