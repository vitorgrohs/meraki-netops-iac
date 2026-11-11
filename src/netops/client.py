"""Dashboard API access, behind a small interface so tests can use a fake."""

from __future__ import annotations

import os
from typing import Any, Protocol

DEFAULT_RULE_COMMENT = "Default rule"


class MerakiClient(Protocol):
    """The subset of the Meraki Dashboard API this tool needs."""

    def get_vlans(self, network: str) -> list[dict[str, Any]]: ...
    def create_vlan(self, network: str, vlan_id: int, fields: dict[str, Any]) -> None: ...
    def update_vlan(self, network: str, vlan_id: int, fields: dict[str, Any]) -> None: ...
    def delete_vlan(self, network: str, vlan_id: int) -> None: ...
    def get_l3_rules(self, network: str) -> list[dict[str, Any]]: ...
    def set_l3_rules(self, network: str, rules: list[dict[str, Any]]) -> None: ...


def strip_default_rule(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The API always appends an implicit 'allow any' rule that cannot be edited."""
    return [r for r in rules if r.get("comment") != DEFAULT_RULE_COMMENT]


class DashboardClient:
    """Real client, built on the official ``meraki`` SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        import meraki  # imported lazily: tests and --simulate don't need it

        key = api_key or os.environ.get("MERAKI_API_KEY")
        if not key:
            raise RuntimeError("set MERAKI_API_KEY (or use --simulate)")
        self._api = meraki.DashboardAPI(
            key,
            suppress_logging=True,
            output_log=False,
            print_console=False,
            caller="meraki-netops-iac",
        )

    def get_vlans(self, network: str) -> list[dict[str, Any]]:
        vlans: list[dict[str, Any]] = self._api.appliance.getNetworkApplianceVlans(network)
        return vlans

    def create_vlan(self, network: str, vlan_id: int, fields: dict[str, Any]) -> None:
        self._api.appliance.createNetworkApplianceVlan(network, vlan_id, **fields)

    def update_vlan(self, network: str, vlan_id: int, fields: dict[str, Any]) -> None:
        self._api.appliance.updateNetworkApplianceVlan(network, vlan_id, **fields)

    def delete_vlan(self, network: str, vlan_id: int) -> None:
        self._api.appliance.deleteNetworkApplianceVlan(network, vlan_id)

    def get_l3_rules(self, network: str) -> list[dict[str, Any]]:
        resp = self._api.appliance.getNetworkApplianceFirewallL3FirewallRules(network)
        rules: list[dict[str, Any]] = resp.get("rules", [])
        return rules

    def set_l3_rules(self, network: str, rules: list[dict[str, Any]]) -> None:
        self._api.appliance.updateNetworkApplianceFirewallL3FirewallRules(
            network, rules=strip_default_rule(rules)
        )
