from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from netops.backup import load_backup, snapshot, snapshot_to_config
from netops.executor import ApplyError, apply
from netops.fake import FakeMerakiClient
from netops.planner import plan
from tests.conftest import NET, make_config


def test_apply_then_second_plan_is_empty(client: FakeMerakiClient, tmp_path: Path) -> None:
    cfg = make_config()
    result = apply(cfg, client, plan(cfg, client), backup_dir=tmp_path)
    assert len(result.applied) == 2
    assert plan(cfg, client) == []  # idempotent


def test_backup_is_taken_before_changes(client: FakeMerakiClient, tmp_path: Path) -> None:
    cfg = make_config()
    result = apply(cfg, client, plan(cfg, client), backup_dir=tmp_path)
    assert result.backup is not None
    snap = load_backup(result.backup)
    assert [v["id"] for v in snap["vlans"]] == [1]  # state *before* VLAN 10 was created
    assert snap["firewall_l3"] == []


def test_nothing_to_do_takes_no_backup(client: FakeMerakiClient, tmp_path: Path) -> None:
    result = apply(make_config(), client, [], backup_dir=tmp_path)
    assert result.backup is None
    assert not any(tmp_path.iterdir())


def test_rollback_restores_previous_state(client: FakeMerakiClient, tmp_path: Path) -> None:
    before = snapshot(client, NET)
    cfg = make_config()
    result = apply(cfg, client, plan(cfg, client), backup_dir=tmp_path)
    assert result.backup is not None

    target = snapshot_to_config(load_backup(result.backup))
    apply(target, client, plan(target, client, prune=True), backup_dir=tmp_path, prune=True)

    after = snapshot(client, NET)
    assert after["vlans"] == before["vlans"]
    assert after["firewall_l3"] == before["firewall_l3"]


class _BrokenClient(FakeMerakiClient):
    def set_l3_rules(self, network: str, rules: list[dict[str, Any]]) -> None:
        raise RuntimeError("API 500")


def test_failure_midway_reports_backup_and_done(tmp_path: Path) -> None:
    client = _BrokenClient()
    cfg = make_config()
    with pytest.raises(ApplyError) as err:
        apply(cfg, client, plan(cfg, client), backup_dir=tmp_path)
    assert err.value.backup.exists()
    assert [a.key for a in err.value.done] == ["10"]  # the VLAN went through first
    assert json.loads(err.value.backup.read_text())["network"] == NET
