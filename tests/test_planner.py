from __future__ import annotations

import pytest

from netops.fake import FakeMerakiClient
from netops.planner import PlanError, plan
from tests.conftest import NET, make_config


def test_fresh_network_plans_create_and_firewall(client: FakeMerakiClient) -> None:
    actions = plan(make_config(), client)
    assert [(a.op, a.resource, a.key) for a in actions] == [
        ("create", "vlan", "10"),
        ("replace", "firewall_l3", "rules"),
    ]


def test_no_changes_when_in_sync(client: FakeMerakiClient) -> None:
    client.create_vlan(
        NET, 10, {"name": "Corp", "subnet": "10.0.10.0/24", "applianceIp": "10.0.10.1"}
    )
    client.set_l3_rules(
        NET,
        [
            {
                "comment": "guest to corp",
                "policy": "deny",
                "protocol": "Any",
                "srcCidr": "10.0.20.0/24",
                "srcPort": "any",
                "destCidr": "10.0.10.0/24",
                "destPort": "Any",
                "syslogEnabled": False,
            }
        ],
    )
    assert plan(make_config(), client) == []


def test_update_lists_only_changed_fields(client: FakeMerakiClient) -> None:
    client.create_vlan(
        NET, 10, {"name": "Old", "subnet": "10.0.10.0/24", "applianceIp": "10.0.10.1"}
    )
    actions = plan(make_config(firewall_l3=None), client)
    assert len(actions) == 1
    assert actions[0].op == "update"
    assert actions[0].changes == {"name": ("Old", "Corp")}


def test_extra_vlan_kept_without_prune(client: FakeMerakiClient) -> None:
    client.create_vlan(
        NET, 99, {"name": "Legacy", "subnet": "10.9.9.0/24", "applianceIp": "10.9.9.1"}
    )
    ops = [(a.op, a.key) for a in plan(make_config(firewall_l3=None), client)]
    assert ("delete", "99") not in ops


def test_prune_deletes_extra_vlan_last(client: FakeMerakiClient) -> None:
    client.create_vlan(
        NET, 99, {"name": "Legacy", "subnet": "10.9.9.0/24", "applianceIp": "10.9.9.1"}
    )
    actions = plan(make_config(), client, prune=True)
    assert actions[-1].op == "delete" and actions[-1].key == "99"


def test_prune_refuses_to_remove_every_vlan(client: FakeMerakiClient) -> None:
    with pytest.raises(PlanError, match="at least one"):
        plan(make_config(vlans=[]), client, prune=True)


def test_unmanaged_firewall_is_ignored(client: FakeMerakiClient) -> None:
    client.set_l3_rules(
        NET,
        [
            {
                "comment": "manual",
                "policy": "deny",
                "protocol": "any",
                "srcCidr": "Any",
                "srcPort": "Any",
                "destCidr": "Any",
                "destPort": "Any",
                "syslogEnabled": False,
            }
        ],
    )
    actions = plan(make_config(firewall_l3=None), client)
    assert all(a.resource != "firewall_l3" for a in actions)


def test_plan_is_read_only(client: FakeMerakiClient) -> None:
    plan(make_config(), client, prune=True)
    assert {op for op, _ in client.calls} <= {"get_vlans", "get_l3_rules"}
