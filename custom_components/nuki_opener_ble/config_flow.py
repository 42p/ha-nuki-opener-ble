"""Config flow: discover the Opener over Bluetooth, pair with it, set options."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    APPLE_MANUFACTURER_ID,
    CONF_APP_ID,
    CONF_AUTH_ID,
    CONF_CLIENT_NAME,
    CONF_INFO_INTERVAL,
    CONF_PAIR_AS_BRIDGE,
    CONF_PIN,
    CONF_POLL_INTERVAL,
    CONF_SHARED_KEY,
    DEFAULT_CLIENT_NAME,
    DEFAULT_INFO_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    ERROR_BAD_PIN,
    ERROR_NOT_PAIRING,
    IBEACON_PREFIX,
    KEYTURNER_SERVICE_UUID,
    OPENER_BEACON_UUID,
    PAIRING_SERVICE_UUID,
    ClientType,
)
from .protocol import NukiDeviceError, NukiError, NukiOpenerClient, async_pair

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


PAIR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIENT_NAME, default=DEFAULT_CLIENT_NAME): str,
        vol.Required(CONF_PAIR_AS_BRIDGE, default=False): bool,
    }
)


class NukiOpenerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nuki Opener BLE."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._title: str | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NukiOpenerOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not is_opener(discovery_info):
            return self.async_abort(reason="not_supported")
        self._address = discovery_info.address
        self._title = _title(discovery_info)
        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_pair()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._address = address
            self._title = _title(self._discovered[address])
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

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        self._address = entry.data[CONF_ADDRESS]
        self._title = entry.title
        return await self.async_step_pair()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._address is not None and self._title is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )
            client_type = (
                ClientType.BRIDGE if user_input[CONF_PAIR_AS_BRIDGE] else ClientType.APP
            )
            if device is None:
                errors["base"] = "cannot_connect"
            else:
                try:
                    result = await async_pair(
                        device, user_input[CONF_CLIENT_NAME], client_type
                    )
                except NukiDeviceError as err:
                    _LOGGER.warning("Pairing rejected: %s", err)
                    errors["base"] = (
                        "not_pairing_mode" if err.code == ERROR_NOT_PAIRING else "pairing_failed"
                    )
                except NukiError as err:
                    _LOGGER.warning("Pairing failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    data = {
                        CONF_ADDRESS: self._address,
                        CONF_AUTH_ID: result.auth_id,
                        CONF_SHARED_KEY: result.shared_key.hex(),
                        CONF_APP_ID: result.app_id,
                    }
                    if self.source == SOURCE_REAUTH:
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(), data=data
                        )
                    return self.async_create_entry(title=self._title, data=data)

        return self.async_show_form(
            step_id="pair",
            data_schema=PAIR_SCHEMA,
            description_placeholders={"name": self._title},
            errors=errors,
        )


class NukiOpenerOptionsFlow(OptionsFlow):
    """Security PIN and polling intervals."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            pin = str(user_input.get(CONF_PIN) or "").strip()
            if pin and not (pin.isdigit() and 0 < int(pin) <= 0xFFFF):
                errors[CONF_PIN] = "invalid_pin"
            elif pin and pin != options.get(CONF_PIN):
                errors = await self._verify_pin(int(pin))
            if not errors:
                return self.async_create_entry(
                    data={
                        CONF_PIN: pin,
                        CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL]),
                        CONF_INFO_INTERVAL: int(user_input[CONF_INFO_INTERVAL]),
                    }
                )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PIN,
                    description={"suggested_value": options.get(CONF_PIN, "")},
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30, max=86400, step=30, unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_INFO_INTERVAL,
                    default=options.get(CONF_INFO_INTERVAL, DEFAULT_INFO_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=300, max=604800, step=300, unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def _verify_pin(self, pin: int) -> dict[str, str]:
        entry = self.config_entry
        coordinator = getattr(entry, "runtime_data", None)
        client = NukiOpenerClient(
            entry.data[CONF_AUTH_ID],
            bytes.fromhex(entry.data[CONF_SHARED_KEY]),
            entry.data[CONF_APP_ID],
            pin,
        )
        device = bluetooth.async_ble_device_from_address(
            self.hass, entry.data[CONF_ADDRESS], connectable=True
        )
        if device is None:
            return {"base": "cannot_connect"}
        try:
            if coordinator is not None:
                async with coordinator.ble_lock:
                    await client.run(device, None, lambda s: s.verify_pin())
            else:
                await client.run(device, None, lambda s: s.verify_pin())
        except NukiDeviceError as err:
            _LOGGER.warning("PIN verification failed: %s", err)
            return {CONF_PIN: "wrong_pin" if err.code == ERROR_BAD_PIN else "cannot_connect"}
        except NukiError as err:
            _LOGGER.warning("PIN verification failed: %s", err)
            return {"base": "cannot_connect"}
        return {}
