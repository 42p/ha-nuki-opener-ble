"""Switches for Ring to Open and Continuous mode."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OpenerAction
from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator
from .entity import NukiOpenerEntity
from .protocol import OpenerState


@dataclass(frozen=True, kw_only=True)
class NukiOpenerSwitchDescription(SwitchEntityDescription):
    is_on_fn: Callable[[OpenerState], bool]
    on_action: OpenerAction
    off_action: OpenerAction


SWITCHES = (
    NukiOpenerSwitchDescription(
        key="ring_to_open",
        translation_key="ring_to_open",
        is_on_fn=lambda s: s.ring_to_open,
        on_action=OpenerAction.ACTIVATE_RTO,
        off_action=OpenerAction.DEACTIVATE_RTO,
    ),
    NukiOpenerSwitchDescription(
        key="continuous_mode",
        translation_key="continuous_mode",
        is_on_fn=lambda s: s.continuous_mode,
        on_action=OpenerAction.ACTIVATE_CONTINUOUS_MODE,
        off_action=OpenerAction.DEACTIVATE_CONTINUOUS_MODE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(NukiOpenerSwitch(entry.runtime_data, d) for d in SWITCHES)


class NukiOpenerSwitch(NukiOpenerEntity, SwitchEntity):
    entity_description: NukiOpenerSwitchDescription

    def __init__(
        self, coordinator: NukiOpenerCoordinator, description: NukiOpenerSwitchDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_action(self.entity_description.on_action)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_action(self.entity_description.off_action)
