"""In-memory stand-in for the Dashboard API, used by tests and ``--simulate``.

It mimics the behaviours that matter for this tool: VLAN 1 exists by default,
the L3 rule list always ends with the implicit default rule, and writes to an
unknown VLAN fail like the real API does.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from netops.client import DEFAULT_RULE_COMMENT, strip_default_rule

_DEFAULT_RULE: dict[str, Any] = {
    "comment": DEFAULT_RULE_COMMENT,
    "policy": "allow",
    "protocol": "Any",
    "srcCidr": "Any",
    "srcPort": "Any",
    "destCidr": "Any",
    "destPort": "Any",
    "syslogEnabled": False,
}


class FakeApiError(RuntimeError):
    pass


def _new_network() -> dict[str, Any]:
    return {
        "vlans": {
            "1": {
                "id": 1,
                "name": "Default",
                "subnet": "192.168.128.0/24",
                "applianceIp": "192.168.128.1",
            }
        },
        "l3_rules": [],
    }


class FakeMerakiClient:
    """Fake client. If ``state_file`` is given, state survives between CLI runs."""

    def __init__(self, state_file: Path | None = None) -> None:
        self._state_file = state_file
        self._state: dict[str, Any] = {}
        if state_file and state_file.exists():
            self._state = json.loads(state_file.read_text(encoding="utf-8"))
        self.calls: list[tuple[str, str]] = []  # (operation, network) — for tests

    # -- helpers ---------------------------------------------------------------
    def _net(self, network: str) -> dict[str, Any]:
        net: dict[str, Any] = self._state.setdefault(network, _new_network())
        return net

    def _save(self) -> None:
        if self._state_file:
            self._state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    # -- VLANs -----------------------------------------------------------------
    def get_vlans(self, network: str) -> list[dict[str, Any]]:
        self.calls.append(("get_vlans", network))
        vlans = self._net(network)["vlans"].values()
        return [copy.deepcopy(v) for v in sorted(vlans, key=lambda v: v["id"])]

    def create_vlan(self, network: str, vlan_id: int, fields: dict[str, Any]) -> None:
        self.calls.append(("create_vlan", network))
        vlans = self._net(network)["vlans"]
        if str(vlan_id) in vlans:
            raise FakeApiError(f"VLAN {vlan_id} already exists")
        vlans[str(vlan_id)] = {"id": vlan_id, **fields}
        self._save()

    def update_vlan(self, network: str, vlan_id: int, fields: dict[str, Any]) -> None:
        self.calls.append(("update_vlan", network))
        vlans = self._net(network)["vlans"]
        if str(vlan_id) not in vlans:
            raise FakeApiError(f"VLAN {vlan_id} not found")
        vlans[str(vlan_id)].update(fields)
        self._save()

    def delete_vlan(self, network: str, vlan_id: int) -> None:
        self.calls.append(("delete_vlan", network))
        vlans = self._net(network)["vlans"]
        if str(vlan_id) not in vlans:
            raise FakeApiError(f"VLAN {vlan_id} not found")
        del vlans[str(vlan_id)]
        self._save()

    # -- L3 firewall -----------------------------------------------------------
    def get_l3_rules(self, network: str) -> list[dict[str, Any]]:
        self.calls.append(("get_l3_rules", network))
        return [*copy.deepcopy(self._net(network)["l3_rules"]), dict(_DEFAULT_RULE)]

    def set_l3_rules(self, network: str, rules: list[dict[str, Any]]) -> None:
        self.calls.append(("set_l3_rules", network))
        self._net(network)["l3_rules"] = copy.deepcopy(strip_default_rule(rules))
        self._save()
