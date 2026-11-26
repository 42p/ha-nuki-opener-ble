"""Nuki Opener over Bluetooth LE."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: NukiOpenerConfigEntry) -> bool:
    """Set up a paired Opener."""
    coordinator = NukiOpenerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.async_handle_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=coordinator.address),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    @callback
    def _update_device() -> None:
        config = coordinator.data.config
        if config is None:
            return
        registry = dr.async_get(hass)
        device = registry.async_get_device(identifiers={(DOMAIN, coordinator.address)})
        if device and (
            device.sw_version != config.firmware_version
            or device.hw_version != config.hardware_revision
        ):
            registry.async_update_device(
                device.id,
                sw_version=config.firmware_version,
                hw_version=config.hardware_revision,
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _update_device()
    entry.async_on_unload(coordinator.async_add_listener(_update_device))
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: NukiOpenerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NukiOpenerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
