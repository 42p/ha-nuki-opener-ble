"""Enumerated Opener settings (requires PIN)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import AdvertisingMode, BatteryType, ButtonPressAction
from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator
from .entity import NukiOpenerEntity


@dataclass(frozen=True, kw_only=True)
class NukiOpenerSelectDescription(SelectEntityDescription):
    enum: type[IntEnum]
    field: str
    advanced: bool = True


SELECTS = (
    NukiOpenerSelectDescription(
        key="single_button_press_action",
        translation_key="button_press_action",
        enum=ButtonPressAction,
        field="single_button_press_action",
    ),
    NukiOpenerSelectDescription(
        key="double_button_press_action",
        translation_key="double_button_press_action",
        enum=ButtonPressAction,
        field="double_button_press_action",
    ),
    NukiOpenerSelectDescription(
        key="battery_type",
        translation_key="battery_type",
        enum=BatteryType,
        field="battery_type",
        entity_registry_enabled_default=False,
    ),
    NukiOpenerSelectDescription(
        key="advertising_mode",
        translation_key="advertising_mode",
        enum=AdvertisingMode,
        field="advertising_mode",
        advanced=False,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.has_pin:
        async_add_entities(NukiOpenerSelect(coordinator, d) for d in SELECTS)


class NukiOpenerSelect(NukiOpenerEntity, SelectEntity):
    entity_description: NukiOpenerSelectDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: NukiOpenerCoordinator, description: NukiOpenerSelectDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = [m.name.lower() for m in description.enum]

    def _source(self):
        d = self.opener
        return d.advanced if self.entity_description.advanced else d.config

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    @property
    def current_option(self) -> str | None:
        if (src := self._source()) is None:
            return None
        value = getattr(src, self.entity_description.field)
        try:
            return self.entity_description.enum(value).name.lower()
        except ValueError:
            return None

    async def async_select_option(self, option: str) -> None:
        value = int(self.entity_description.enum[option.upper()])
        field = self.entity_description.field
        if self.entity_description.advanced:
            await self.coordinator.async_set_advanced_config(**{field: value})
        else:
            await self.coordinator.async_set_config(**{field: value})
