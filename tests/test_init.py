"""Integration tests: entities, actions, doorbell, options, pairing flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.nuki_opener_ble import protocol as p
from custom_components.nuki_opener_ble.const import (
    CONF_APP_ID,
    CONF_AUTH_ID,
    CONF_INFO_INTERVAL,
    CONF_PIN,
    CONF_POLL_INTERVAL,
    CONF_SHARED_KEY,
    DOMAIN,
    RING_EVENT,
)

from .fake_opener import FakeConnection, FakeOpener

ADDRESS = "AA:BB:CC:DD:EE:FF"
DEVICE = SimpleNamespace(address=ADDRESS, name="Nuki_Opener_1234")


@pytest.fixture
def opener(enable_bluetooth) -> FakeOpener:
    device = FakeOpener()
    FakeConnection.opener = device
    with (
        patch.object(p, "_Connection", FakeConnection),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=DEVICE,
        ),
    ):
        yield device


async def _entry(hass: HomeAssistant, opener: FakeOpener, pin: str = "1234") -> MockConfigEntry:
    paired = await p.async_pair(DEVICE, "Home Assistant")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nuki Opener",
        unique_id=ADDRESS,
        data={
            CONF_ADDRESS: ADDRESS,
            CONF_AUTH_ID: paired.auth_id,
            CONF_SHARED_KEY: paired.shared_key.hex(),
            CONF_APP_ID: paired.app_id,
        },
        options={CONF_PIN: pin, CONF_POLL_INTERVAL: 600, CONF_INFO_INTERVAL: 3600},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_entities_and_actions(hass: HomeAssistant, opener: FakeOpener) -> None:
    await _entry(hass, opener)

    assert hass.states.get("lock.nuki_opener").state == "locked"
    assert hass.states.get("sensor.nuki_opener_state").state == "locked"
    assert hass.states.get("sensor.nuki_opener_mode").state == "door"
    assert hass.states.get("sensor.nuki_opener_battery_voltage").state == "4.712"
    assert hass.states.get("switch.nuki_opener_led_flash").state == "on"
    assert hass.states.get("number.nuki_opener_ring_to_open_timeout").state == "20"
    assert hass.states.get("select.nuki_opener_button_single_press").state == "toggle_rto"

    await hass.services.async_call("lock", "unlock", {ATTR_ENTITY_ID: "lock.nuki_opener"}, blocking=True)
    assert hass.states.get("lock.nuki_opener").state == "unlocked"
    assert hass.states.get("switch.nuki_opener_ring_to_open").state == "on"

    await hass.services.async_call("lock", "open", {ATTR_ENTITY_ID: "lock.nuki_opener"}, blocking=True)
    assert hass.states.get("lock.nuki_opener").state == "open"

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.nuki_opener_continuous_mode"}, blocking=True
    )
    assert opener.mode == 3
    assert hass.states.get("switch.nuki_opener_continuous_mode").state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.nuki_opener_led_flash"}, blocking=True
    )
    assert opener.led == 0
    assert hass.states.get("switch.nuki_opener_led_flash").state == "off"

    await hass.services.async_call(
        "number", "set_value",
        {ATTR_ENTITY_ID: "number.nuki_opener_ring_to_open_timeout", "value": 30},
        blocking=True,
    )
    assert opener.rto_timeout == 30

    await hass.services.async_call(
        "select", "select_option",
        {ATTR_ENTITY_ID: "select.nuki_opener_button_single_press", "option": "open"},
        blocking=True,
    )
    assert opener.single_press == 7

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: "button.nuki_opener_sync_time"}, blocking=True
    )
    assert opener.time_set is not None


async def test_doorbell_from_log(hass: HomeAssistant, opener: FakeOpener) -> None:
    entry = await _entry(hass, opener)
    events = []
    hass.bus.async_listen(RING_EVENT, events.append)

    opener.add_log(0x06, bytes([1, 0, 0, 0, 1, 0, 0, 0]))  # ring with RTO active
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["type"] == "ring_opened"
    state = hass.states.get("event.nuki_opener_doorbell")
    assert state.attributes["event_type"] == "ring_opened"
    assert hass.states.get("sensor.nuki_opener_last_ring").state not in ("unknown", "unavailable")

    await entry.runtime_data.async_refresh()  # same log again: no new event
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_without_pin(hass: HomeAssistant, opener: FakeOpener) -> None:
    await _entry(hass, opener, pin="")
    assert hass.states.get("switch.nuki_opener_led_flash") is None
    assert hass.states.get("lock.nuki_opener").state == "locked"
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.nuki_opener_continuous_mode"}, blocking=True
    )
    assert opener.mode == 3


async def test_options_flow_verifies_pin(hass: HomeAssistant, opener: FakeOpener) -> None:
    entry = await _entry(hass, opener, pin="")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PIN: "4321", CONF_POLL_INTERVAL: 600, CONF_INFO_INTERVAL: 3600},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PIN: "wrong_pin"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PIN: "1234", CONF_POLL_INTERVAL: 600, CONF_INFO_INTERVAL: 3600},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("switch.nuki_opener_led_flash") is not None


async def test_pairing_flow(hass: HomeAssistant, opener: FakeOpener) -> None:
    from custom_components.nuki_opener_ble.const import OPENER_BEACON_UUID

    info = SimpleNamespace(
        address=ADDRESS,
        name="Nuki_Opener_1234",
        service_uuids=[],
        manufacturer_data={0x004C: b"\x02\x15" + OPENER_BEACON_UUID + b"\x00\x00\x00\x00\xc4"},
        device=DEVICE,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "bluetooth"}, data=info
    )
    assert result["step_id"] == "pair"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"client_name": "Home Assistant", "pair_as_bridge": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AUTH_ID] == opener.AUTH_ID
    await hass.async_block_till_done()


async def test_doorbell_without_pin(hass: HomeAssistant, opener: FakeOpener) -> None:
    """Beacon flags a change while nothing visible changed: a ring while locked."""
    entry = await _entry(hass, opener, pin="")
    coordinator = entry.runtime_data
    events = []
    hass.bus.async_listen(RING_EVENT, events.append)

    adv = SimpleNamespace(
        rssi=-71,
        manufacturer_data={0x004C: b"\x02\x15" + bytes(20) + b"\xc5"},
    )
    coordinator.async_handle_advertisement(adv, None)
    await hass.async_block_till_done()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert [e.data["type"] for e in events] == ["ring"]
    assert hass.states.get("sensor.nuki_opener_signal_strength").state == "-71"
