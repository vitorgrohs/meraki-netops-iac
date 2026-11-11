"""Compare desired state with the live network and produce an ordered list of actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from netops.client import MerakiClient, strip_default_rule
from netops.models import NetworkConfig

Op = Literal["create", "update", "delete", "replace"]
Resource = Literal["vlan", "firewall_l3"]

VLAN_FIELDS = ("name", "subnet", "applianceIp")
RULE_FIELDS = (
    "comment",
    "policy",
    "protocol",
    "srcCidr",
    "srcPort",
    "destCidr",
    "destPort",
    "syslogEnabled",
)


@dataclass(frozen=True)
class Action:
    op: Op
    resource: Resource
    key: str
    before: Any = None
    after: Any = None
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)


class PlanError(ValueError):
    pass


def _vlan_view(vlan: dict[str, Any]) -> dict[str, Any]:
    return {k: vlan.get(k) for k in VLAN_FIELDS}


def normalize_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Make API rules and desired rules comparable (the API is loose with casing)."""
    out = {k: rule.get(k) for k in RULE_FIELDS}
    out["comment"] = out["comment"] or ""
    out["policy"] = str(out["policy"]).lower()
    out["protocol"] = str(out["protocol"]).lower()
    for k in ("srcCidr", "srcPort", "destCidr", "destPort"):
        value = str(out[k] or "Any")
        out[k] = "Any" if value.lower() == "any" else value.replace(" ", "")
    out["syslogEnabled"] = bool(out["syslogEnabled"])
    return out


def plan(config: NetworkConfig, client: MerakiClient, *, prune: bool = False) -> list[Action]:
    """Return the actions needed to move the network to ``config``.

    Order: creates, updates, firewall replacement, deletes — so a rule that
    references a new VLAN subnet is only pushed after the VLAN exists, and
    nothing is removed before its replacement is in place.
    """
    net = config.network
    current = {int(v["id"]): _vlan_view(v) for v in client.get_vlans(net)}
    desired = {v.id: v.to_api() for v in config.vlans}

    creates: list[Action] = []
    updates: list[Action] = []
    deletes: list[Action] = []

    for vid, want in sorted(desired.items()):
        have = current.get(vid)
        if have is None:
            creates.append(Action("create", "vlan", str(vid), after=want))
        elif have != want:
            diff = {k: (have[k], want[k]) for k in VLAN_FIELDS if have[k] != want[k]}
            updates.append(
                Action("update", "vlan", str(vid), before=have, after=want, changes=diff)
            )

    if prune:
        extra = sorted(set(current) - set(desired))
        if extra and not desired:
            raise PlanError(f"{net}: refusing to prune every VLAN (Meraki needs at least one)")
        deletes = [Action("delete", "vlan", str(v), before=current[v]) for v in extra]

    firewall: list[Action] = []
    if config.firewall_l3 is not None:
        want_rules = [normalize_rule(r.to_api()) for r in config.firewall_l3]
        have_rules = [normalize_rule(r) for r in strip_default_rule(client.get_l3_rules(net))]
        if want_rules != have_rules:
            firewall.append(
                Action("replace", "firewall_l3", "rules", before=have_rules, after=want_rules)
            )

    return [*creates, *updates, *firewall, *deletes]
