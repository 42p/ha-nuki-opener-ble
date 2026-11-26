"""Buttons: open door, refresh, and (with PIN) time sync and reboot."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OpenerAction
from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator
from .entity import NukiOpenerEntity


@dataclass(frozen=True, kw_only=True)
class NukiOpenerButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[NukiOpenerCoordinator], Awaitable[None]]
    needs_pin: bool = False


BUTTONS = (
    NukiOpenerButtonDescription(
        key="open",
        translation_key="open",
        press_fn=lambda c: c.async_action(OpenerAction.ELECTRIC_STRIKE_ACTUATION),
    ),
    NukiOpenerButtonDescription(
        key="refresh",
        translation_key="refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda c: c.async_refresh_info(),
    ),
    NukiOpenerButtonDescription(
        key="sync_time",
        translation_key="sync_time",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_sync_time(),
        needs_pin=True,
    ),
    NukiOpenerButtonDescription(
        key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_reboot(),
        needs_pin=True,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        NukiOpenerButton(coordinator, d)
        for d in BUTTONS
        if coordinator.has_pin or not d.needs_pin
    )


class NukiOpenerButton(NukiOpenerEntity, ButtonEntity):
    entity_description: NukiOpenerButtonDescription

    def __init__(
        self, coordinator: NukiOpenerCoordinator, description: NukiOpenerButtonDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
