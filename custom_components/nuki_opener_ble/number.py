"""Numeric Opener settings (advanced config, requires PIN)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator
from .entity import NukiOpenerEntity


@dataclass(frozen=True, kw_only=True)
class NukiOpenerNumberDescription(NumberEntityDescription):
    field: str


NUMBERS = (
    NukiOpenerNumberDescription(
        key="rto_timeout",
        translation_key="rto_timeout",
        field="rto_timeout",
        native_min_value=5,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    NukiOpenerNumberDescription(
        key="electric_strike_duration",
        translation_key="electric_strike_duration",
        field="electric_strike_duration",
        native_min_value=1000,
        native_max_value=30000,
        native_step=500,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
    ),
    NukiOpenerNumberDescription(
        key="electric_strike_delay",
        translation_key="electric_strike_delay",
        field="electric_strike_delay",
        native_min_value=0,
        native_max_value=30000,
        native_step=500,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
    ),
    NukiOpenerNumberDescription(
        key="doorbell_suppression_duration",
        translation_key="doorbell_suppression_duration",
        field="doorbell_suppression_duration",
        native_min_value=500,
        native_max_value=10000,
        native_step=100,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        entity_registry_enabled_default=False,
    ),
    NukiOpenerNumberDescription(
        key="sound_level",
        translation_key="sound_level",
        field="sound_level",
        native_min_value=0,
        native_max_value=255,
        native_step=1,
        mode=NumberMode.SLIDER,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.has_pin:
        async_add_entities(NukiOpenerNumber(coordinator, d) for d in NUMBERS)


class NukiOpenerNumber(NukiOpenerEntity, NumberEntity):
    entity_description: NukiOpenerNumberDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: NukiOpenerCoordinator, description: NukiOpenerNumberDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.opener.advanced is not None

    @property
    def native_value(self) -> float | None:
        if (adv := self.opener.advanced) is None:
            return None
        return getattr(adv, self.entity_description.field)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_advanced_config(
            **{self.entity_description.field: int(value)}
        )
