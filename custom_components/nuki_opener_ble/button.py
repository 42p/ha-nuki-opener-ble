"""Button that actuates the electric strike (buzzes the door open)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OpenerAction
from .coordinator import NukiOpenerConfigEntry
from .entity import NukiOpenerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NukiOpenerOpenButton(entry.runtime_data, "open")])


class NukiOpenerOpenButton(NukiOpenerEntity, ButtonEntity):
    _attr_translation_key = "open"

    async def async_press(self) -> None:
        await self.coordinator.async_action(OpenerAction.ELECTRIC_STRIKE_ACTUATION)
