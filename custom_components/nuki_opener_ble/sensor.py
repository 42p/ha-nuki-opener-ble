"""Sensors mirroring what Nuki Hub publishes for an Opener."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CompletionStatus,
    OpenerAction,
    OpenerLockState,
    OpenerMode,
    Trigger,
)
from .coordinator import NukiOpenerConfigEntry, NukiOpenerCoordinator, OpenerData
from .entity import NukiOpenerEntity


def _name(enum_cls: type[IntEnum], value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return enum_cls(value).name.lower()
    except ValueError:
        return None


def _options(enum_cls: type[IntEnum]) -> list[str]:
    return [m.name.lower() for m in enum_cls]


@dataclass(frozen=True, kw_only=True)
class NukiOpenerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[OpenerData], Any]
    attrs_fn: Callable[[OpenerData], dict[str, Any] | None] | None = None


def _enum_sensor(key: str, enum_cls: type[IntEnum], getter, **kwargs) -> NukiOpenerSensorDescription:
    return NukiOpenerSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=_options(enum_cls),
        value_fn=lambda d: _name(enum_cls, getter(d)),
        **kwargs,
    )


SENSORS = (
    _enum_sensor("lock_state", OpenerLockState, lambda d: d.state.lock_state),
    _enum_sensor("mode", OpenerMode, lambda d: d.state.mode),
    _enum_sensor(
        "trigger", Trigger, lambda d: d.state.trigger,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_sensor(
        "last_action", OpenerAction, lambda d: d.state.last_action,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_sensor(
        "last_action_trigger", Trigger, lambda d: d.state.last_action_trigger,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_sensor(
        "last_action_completion", CompletionStatus, lambda d: d.state.last_action_completion,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NukiOpenerSensorDescription(
        key="ring_to_open_timer",
        translation_key="ring_to_open_timer",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda d: (
            d.state.ring_to_open_timer
            if d.state.ring_to_open and d.state.ring_to_open_timer != 0xFF
            else 0
        ),
    ),
    NukiOpenerSensorDescription(
        key="last_ring",
        translation_key="last_ring",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_ring,
    ),
    NukiOpenerSensorDescription(
        key="last_log",
        translation_key="last_log",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_log.timestamp if d.last_log else None,
        attrs_fn=lambda d: d.last_log.describe() if d.last_log else None,
    ),
    NukiOpenerSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery.voltage if d.battery else None,
    ),
    NukiOpenerSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.rssi,
    ),
    NukiOpenerSensorDescription(
        key="device_time",
        translation_key="device_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.state.device_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        NukiOpenerSensor(coordinator, d)
        for d in SENSORS
        if d.key != "last_log" or coordinator.has_pin
    )


class NukiOpenerSensor(NukiOpenerEntity, SensorEntity):
    entity_description: NukiOpenerSensorDescription

    def __init__(
        self, coordinator: NukiOpenerCoordinator, description: NukiOpenerSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | float | datetime | None:
        return self.entity_description.value_fn(self.opener)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.opener)
