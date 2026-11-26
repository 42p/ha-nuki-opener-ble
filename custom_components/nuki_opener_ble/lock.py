"""Lock entity: locked = Ring to Open off, unlock = Ring to Open on, open = buzz the door."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OpenerAction, OpenerLockState
from .coordinator import NukiOpenerConfigEntry
from .entity import NukiOpenerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiOpenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NukiOpenerLock(entry.runtime_data, "lock")])


class NukiOpenerLock(NukiOpenerEntity, LockEntity):
    """Same semantics as the official Nuki integration for the Opener."""

    _attr_name = None
    _attr_supported_features = LockEntityFeature.OPEN

    @property
    def is_locked(self) -> bool:
        state = self.opener.state
        return not (state.ring_to_open or state.continuous_mode)

    @property
    def is_open(self) -> bool:
        return self.opener.state.lock_state == OpenerLockState.OPEN

    @property
    def is_opening(self) -> bool:
        return self.opener.state.lock_state == OpenerLockState.OPENING

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_action(OpenerAction.ACTIVATE_RTO)

    async def async_lock(self, **kwargs: Any) -> None:
        if self.opener.state.continuous_mode:
            await self.coordinator.async_action(OpenerAction.DEACTIVATE_CM)
        if self.opener.state.ring_to_open:
            await self.coordinator.async_action(OpenerAction.DEACTIVATE_RTO)

    async def async_open(self, **kwargs: Any) -> None:
        await self.coordinator.async_action(OpenerAction.ELECTRIC_STRIKE_ACTUATION)
