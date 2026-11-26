"""Nuki Opener over Bluetooth LE."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.LOCK, Platform.SWITCH]


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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NukiOpenerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
