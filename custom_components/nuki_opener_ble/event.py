"""Doorbell event entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import (
    EventDeviceClass,
    EventEntity,
    EventEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NukiOpenerConfigEntry
from .entity import NukiOpenerEntity

DESCRIPTION = EventEntityDescription(
    key="doorbell",
    translation_key="doorbell",
    device_class=EventDeviceClass.DOORBELL,
    event_types=["ring", "ring_opened"],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NukiOpenerDoorbell(entry.runtime_data, DESCRIPTION.key)])


class NukiOpenerDoorbell(NukiOpenerEntity, EventEntity):
    entity_description = DESCRIPTION

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_ring_listener(self._on_ring))

    @callback
    def _on_ring(self, event_type: str, details: dict[str, Any]) -> None:
        self._trigger_event(event_type, details)
        self.async_write_ha_state()
