"""Protocol tests against the in-memory Opener."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.nuki_opener_ble import protocol as p
from custom_components.nuki_opener_ble.const import OpenerAction, OpenerLockState, OpenerMode

from .fake_opener import FakeConnection, FakeOpener


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> FakeOpener:
    device = FakeOpener()
    FakeConnection.opener = device
    monkeypatch.setattr(p, "_Connection", FakeConnection)
    return device


async def _paired(opener: FakeOpener, pin: int | None = None) -> p.NukiOpenerClient:
    result = await p.async_pair(SimpleNamespace(address="AA"), "Home Assistant")
    assert result.shared_key == opener.key
    assert result.auth_id == opener.AUTH_ID
    return p.NukiOpenerClient(result.auth_id, result.shared_key, result.app_id, pin)


def test_crc() -> None:
    assert p.crc16(b"123456789") == 0x29B1


async def test_state_and_actions(opener: FakeOpener) -> None:
    client = await _paired(opener)

    state = await client.run(None, None, lambda s: s.state())
    assert state.lock_state == OpenerLockState.LOCKED
    assert state.mode == OpenerMode.DOOR
    assert not state.ring_to_open

    async def activate(s: p.OpenerSession):
        await s.lock_action(OpenerAction.ACTIVATE_RTO)
        return await s.state()

    state = await client.run(None, None, activate)
    assert state.ring_to_open


async def test_info(opener: FakeOpener) -> None:
    client = await _paired(opener)

    async def job(s: p.OpenerSession):
        return await s.battery_report(), await s.config(), await s.advanced_config()

    battery, config, advanced = await client.run(None, None, job)
    assert battery.voltage == pytest.approx(4.712)
    assert config.name == "Haustuer"
    assert config.firmware_version == "1.8.22"
    assert config.timezone_id == 37
    assert advanced.rto_timeout == 20
    assert advanced.writable


async def test_pin_commands(opener: FakeOpener) -> None:
    client = await _paired(opener, pin=1234)
    opener.add_log(0x06, bytes([0, 0, 0, 0, 1, 0, 0, 0]))
    opener.add_log(0x02, bytes([3, 1, 0, 0]))

    async def job(s: p.OpenerSession):
        await s.verify_pin()
        await s.lock_action(OpenerAction.ACTIVATE_CM)
        cm = (await s.state()).continuous_mode
        config = await s.config()
        await s.set_config(config.build_set_payload(led_flash_enabled=False))
        adv = await s.advanced_config()
        await s.set_advanced_config(adv.build_set_payload(rto_timeout=45))
        await s.update_time()
        logs = await s.log_entries(5)
        return cm, logs

    cm, logs = await client.run(None, None, job)
    assert cm
    assert opener.led == 0
    assert opener.rto_timeout == 45
    assert opener.time_set is not None
    assert [e.index for e in logs] == [102, 101]
    assert logs[1].is_ring and not logs[1].ring_opened


async def test_bad_pin(opener: FakeOpener) -> None:
    client = await _paired(opener, pin=9999)
    with pytest.raises(p.NukiDeviceError) as err:
        await client.run(None, None, lambda s: s.verify_pin())
    assert err.value.code == 0x21


async def test_pin_required(opener: FakeOpener) -> None:
    client = await _paired(opener)
    with pytest.raises(p.NukiError, match="PIN"):
        await client.run(None, None, lambda s: s.update_time())
