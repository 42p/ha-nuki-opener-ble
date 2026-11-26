"""Binary sensors: battery critical, keypad battery critical."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator, OpenerData
from .entity import NukiOpenerEntity


@dataclass(frozen=True, kw_only=True)
class NukiOpenerBinaryDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[OpenerData], bool | None]


BINARY_SENSORS = (
    NukiOpenerBinaryDescription(
        key="battery_critical",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.state.battery_critical,
    ),
    NukiOpenerBinaryDescription(
        key="keypad_battery_critical",
        translation_key="keypad_battery_critical",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.state.keypad_battery_critical,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities = [NukiOpenerBinarySensor(coordinator, BINARY_SENSORS[0])]
    if coordinator.data.config is not None and coordinator.data.config.has_keypad:
        entities.append(NukiOpenerBinarySensor(coordinator, BINARY_SENSORS[1]))
    async_add_entities(entities)


class NukiOpenerBinarySensor(NukiOpenerEntity, BinarySensorEntity):
    entity_description: NukiOpenerBinaryDescription

    def __init__(
        self, coordinator: NukiOpenerCoordinator, description: NukiOpenerBinaryDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.opener)
