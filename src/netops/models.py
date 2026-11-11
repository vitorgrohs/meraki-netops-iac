"""Desired-state models, loaded from YAML and validated with Pydantic."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network, ip_network
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Vlan(BaseModel):
    """An MX appliance VLAN."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int = Field(ge=1, le=4094)
    name: str = Field(min_length=1, max_length=64)
    subnet: IPv4Network
    appliance_ip: IPv4Address

    @model_validator(mode="after")
    def _ip_inside_subnet(self) -> Vlan:
        if self.appliance_ip not in self.subnet:
            raise ValueError(
                f"VLAN {self.id}: appliance_ip {self.appliance_ip} is outside {self.subnet}"
            )
        return self

    def to_api(self) -> dict[str, Any]:
        """Fields compared and sent to the Dashboard API."""
        return {
            "name": self.name,
            "subnet": str(self.subnet),
            "applianceIp": str(self.appliance_ip),
        }


def _cidr_or_any(value: str) -> str:
    if value.lower() == "any":
        return "Any"
    parts = [p.strip() for p in value.split(",")]
    for part in parts:
        ip_network(part, strict=False)  # raises ValueError if invalid
    return ",".join(parts)


def _port_or_any(value: str) -> str:
    if value.lower() == "any":
        return "Any"
    for part in value.split(","):
        bounds = part.strip().split("-")
        if not all(b.isdigit() and 1 <= int(b) <= 65535 for b in bounds) or len(bounds) > 2:
            raise ValueError(f"invalid port or range: {part!r}")
    return value.replace(" ", "")


class FirewallRule(BaseModel):
    """An MX layer-3 outbound firewall rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    comment: str = ""
    policy: Literal["allow", "deny"]
    protocol: Literal["tcp", "udp", "icmp", "icmp6", "any"] = "any"
    src_cidr: str = "Any"
    src_port: str = "Any"
    dest_cidr: str = "Any"
    dest_port: str = "Any"
    syslog_enabled: bool = False

    @field_validator("src_cidr", "dest_cidr")
    @classmethod
    def _check_cidr(cls, v: str) -> str:
        return _cidr_or_any(v)

    @field_validator("src_port", "dest_port")
    @classmethod
    def _check_port(cls, v: str) -> str:
        return _port_or_any(v)

    @model_validator(mode="after")
    def _ports_need_tcp_udp(self) -> FirewallRule:
        if self.protocol not in ("tcp", "udp") and (
            self.src_port != "Any" or self.dest_port != "Any"
        ):
            raise ValueError(f"rule {self.comment!r}: ports only apply to tcp/udp")
        return self

    def to_api(self) -> dict[str, Any]:
        return {
            "comment": self.comment,
            "policy": self.policy,
            "protocol": self.protocol,
            "srcCidr": self.src_cidr,
            "srcPort": self.src_port,
            "destCidr": self.dest_cidr,
            "destPort": self.dest_port,
            "syslogEnabled": self.syslog_enabled,
        }


class NetworkConfig(BaseModel):
    """Desired state of one Meraki network.

    ``firewall_l3 = None`` means the rules are not managed by this file;
    an empty list means "no custom rules".
    """

    model_config = ConfigDict(extra="forbid")

    network: str = Field(min_length=1)
    vlans: list[Vlan] = Field(default_factory=list)
    firewall_l3: list[FirewallRule] | None = None

    @model_validator(mode="after")
    def _unique_vlans(self) -> NetworkConfig:
        ids = [v.id for v in self.vlans]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicated VLAN ids: {dupes}")
        subnets = [v.subnet for v in self.vlans]
        for i, a in enumerate(subnets):
            for b in subnets[i + 1 :]:
                if a.overlaps(b):
                    raise ValueError(f"overlapping VLAN subnets: {a} and {b}")
        return self


def load_config(path: Path) -> NetworkConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return NetworkConfig.model_validate(data)


def load_configs(path: Path) -> list[tuple[Path, NetworkConfig]]:
    """Load one YAML file, or every ``*.yaml``/``*.yml`` file in a directory."""
    files = sorted([*path.glob("*.yaml"), *path.glob("*.yml")]) if path.is_dir() else [path]
    if not files:
        raise FileNotFoundError(f"no YAML files found in {path}")
    configs = [(f, load_config(f)) for f in files]
    networks = [c.network for _, c in configs]
    dupes = sorted({n for n in networks if networks.count(n) > 1})
    if dupes:
        raise ValueError(f"the same network is defined in more than one file: {dupes}")
    return configs
