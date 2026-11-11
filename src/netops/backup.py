"""Point-in-time snapshots of the managed resources, used for rollback."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netops.client import MerakiClient, strip_default_rule
from netops.models import FirewallRule, NetworkConfig, Vlan
from netops.planner import VLAN_FIELDS, normalize_rule


def snapshot(client: MerakiClient, network: str) -> dict[str, Any]:
    vlans = [
        {"id": int(v["id"]), **{k: v.get(k) for k in VLAN_FIELDS}}
        for v in client.get_vlans(network)
    ]
    rules = [normalize_rule(r) for r in strip_default_rule(client.get_l3_rules(network))]
    return {
        "network": network,
        "taken_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "vlans": sorted(vlans, key=lambda v: v["id"]),
        "firewall_l3": rules,
    }


def save_backup(snap: dict[str, Any], backup_dir: Path) -> Path:
    folder: Path = backup_dir / str(snap["network"])
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = folder / f"{stamp}.json"
    path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_backup(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not {"network", "vlans", "firewall_l3"} <= data.keys():
        raise ValueError(f"{path} is not a netops backup")
    return data


def snapshot_to_config(snap: dict[str, Any]) -> NetworkConfig:
    """Turn a backup back into a desired state, so rollback reuses plan/apply."""
    vlans = [
        Vlan(id=v["id"], name=v["name"], subnet=v["subnet"], appliance_ip=v["applianceIp"])
        for v in snap["vlans"]
    ]
    rules = [
        FirewallRule(
            comment=r["comment"],
            policy=r["policy"],
            protocol=r["protocol"],
            src_cidr=r["srcCidr"],
            src_port=r["srcPort"],
            dest_cidr=r["destCidr"],
            dest_port=r["destPort"],
            syslog_enabled=r["syslogEnabled"],
        )
        for r in snap["firewall_l3"]
    ]
    return NetworkConfig(network=snap["network"], vlans=vlans, firewall_l3=rules)
