"""Diagnostics for the Nuki Opener BLE integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PIN, CONF_SHARED_KEY
from .coordinator import NukiOpenerConfigEntry

TO_REDACT = {CONF_SHARED_KEY, CONF_PIN, "latitude", "longitude"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NukiOpenerConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "pin_in_use": coordinator.has_pin,
            "state": asdict(data.state),
            "battery": asdict(data.battery) if data.battery else None,
            "config": data.config.as_dict() if data.config else None,
            "advanced_config": data.advanced.as_dict() if data.advanced else None,
            "last_log": data.last_log.describe() if data.last_log else None,
            "rssi": data.rssi,
        },
        TO_REDACT,
    )
