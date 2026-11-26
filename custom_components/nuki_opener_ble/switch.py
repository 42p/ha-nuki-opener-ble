"""Switches: Ring to Open, continuous mode and (with PIN) device settings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OpenerAction
from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator, OpenerData
from .entity import NukiOpenerEntity


@dataclass(frozen=True, kw_only=True)
class NukiOpenerSwitchDescription(SwitchEntityDescription):
    is_on_fn: Callable[[OpenerData], bool | None]
    set_fn: Callable[[NukiOpenerCoordinator, bool], Awaitable[None]]
    needs_pin: bool = False


def _action(on: OpenerAction, off: OpenerAction):
    return lambda c, value: c.async_action(on if value else off)


def _config(field: str):
    return lambda c, value: c.async_set_config(**{field: value})


def _advanced(field: str):
    return lambda c, value: c.async_set_advanced_config(**{field: value})


def _cfg(field: str):
    return lambda d: getattr(d.config, field) if d.config else None


def _adv(field: str):
    return lambda d: getattr(d.advanced, field) if d.advanced else None


SWITCHES = (
    NukiOpenerSwitchDescription(
        key="ring_to_open",
        translation_key="ring_to_open",
        is_on_fn=lambda d: d.state.ring_to_open,
        set_fn=_action(OpenerAction.ACTIVATE_RTO, OpenerAction.DEACTIVATE_RTO),
    ),
    NukiOpenerSwitchDescription(
        key="continuous_mode",
        translation_key="continuous_mode",
        is_on_fn=lambda d: d.state.continuous_mode,
        set_fn=_action(OpenerAction.ACTIVATE_CM, OpenerAction.DEACTIVATE_CM),
    ),
    NukiOpenerSwitchDescription(
        key="led_flash",
        translation_key="led_flash",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_cfg("led_flash_enabled"),
        set_fn=_config("led_flash_enabled"),
        needs_pin=True,
    ),
    NukiOpenerSwitchDescription(
        key="button_enabled",
        translation_key="button_enabled",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_cfg("button_enabled"),
        set_fn=_config("button_enabled"),
        needs_pin=True,
    ),
    NukiOpenerSwitchDescription(
        key="pairing_enabled",
        translation_key="pairing_enabled",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_cfg("pairing_enabled"),
        set_fn=_config("pairing_enabled"),
        needs_pin=True,
        entity_registry_enabled_default=False,
    ),
    NukiOpenerSwitchDescription(
        key="disable_rto_after_ring",
        translation_key="disable_rto_after_ring",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_adv("disable_rto_after_ring"),
        set_fn=_advanced("disable_rto_after_ring"),
        needs_pin=True,
    ),
    NukiOpenerSwitchDescription(
        key="random_electric_strike_delay",
        translation_key="random_electric_strike_delay",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_adv("random_electric_strike_delay"),
        set_fn=_advanced("random_electric_strike_delay"),
        needs_pin=True,
        entity_registry_enabled_default=False,
    ),
    NukiOpenerSwitchDescription(
        key="automatic_battery_type_detection",
        translation_key="automatic_battery_type_detection",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=_adv("automatic_battery_type_detection"),
        set_fn=_advanced("automatic_battery_type_detection"),
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
        NukiOpenerSwitch(coordinator, d)
        for d in SWITCHES
        if coordinator.has_pin or not d.needs_pin
    )


class NukiOpenerSwitch(NukiOpenerEntity, SwitchEntity):
    entity_description: NukiOpenerSwitchDescription

    def __init__(
        self, coordinator: NukiOpenerCoordinator, description: NukiOpenerSwitchDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.opener)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, False)
