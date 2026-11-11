from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from netops.models import FirewallRule, Vlan, load_configs
from tests.conftest import make_config


def test_example_network_is_valid() -> None:
    configs = load_configs(Path("networks"))
    assert configs, "the example network should load"


def test_appliance_ip_must_be_inside_subnet() -> None:
    with pytest.raises(ValidationError, match="outside"):
        Vlan(id=10, name="x", subnet="10.0.0.0/24", appliance_ip="10.0.1.1")  # type: ignore[arg-type]


def test_vlan_id_range() -> None:
    with pytest.raises(ValidationError):
        Vlan(id=4095, name="x", subnet="10.0.0.0/24", appliance_ip="10.0.0.1")  # type: ignore[arg-type]


def test_duplicate_vlan_ids_rejected() -> None:
    vlan = {"id": 10, "name": "a", "subnet": "10.0.0.0/24", "appliance_ip": "10.0.0.1"}
    with pytest.raises(ValidationError, match="duplicated"):
        make_config(
            vlans=[vlan, {**vlan, "name": "b", "subnet": "10.0.1.0/24", "appliance_ip": "10.0.1.1"}]
        )


def test_overlapping_subnets_rejected() -> None:
    with pytest.raises(ValidationError, match="overlapping"):
        make_config(
            vlans=[
                {"id": 10, "name": "a", "subnet": "10.0.0.0/16", "appliance_ip": "10.0.0.1"},
                {"id": 20, "name": "b", "subnet": "10.0.5.0/24", "appliance_ip": "10.0.5.1"},
            ]
        )


def test_rule_normalizes_any_and_validates_cidr() -> None:
    rule = FirewallRule(policy="deny", src_cidr="any", dest_cidr="10.0.0.0/24, 10.0.1.0/24")
    assert rule.src_cidr == "Any"
    assert rule.dest_cidr == "10.0.0.0/24,10.0.1.0/24"
    with pytest.raises(ValidationError):
        FirewallRule(policy="deny", src_cidr="10.0.0.300/24")


def test_ports_only_for_tcp_udp() -> None:
    FirewallRule(policy="allow", protocol="tcp", dest_port="443")
    FirewallRule(policy="allow", protocol="udp", dest_port="1000-2000")
    with pytest.raises(ValidationError, match="ports only apply"):
        FirewallRule(policy="allow", protocol="any", dest_port="443")
    with pytest.raises(ValidationError):
        FirewallRule(policy="allow", protocol="tcp", dest_port="70000")


def test_same_network_in_two_files_rejected(tmp_path: Path) -> None:
    body = "network: N_dup\nvlans: []\n"
    (tmp_path / "a.yaml").write_text(body)
    (tmp_path / "b.yaml").write_text(body)
    with pytest.raises(ValueError, match="more than one file"):
        load_configs(tmp_path)
