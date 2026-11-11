from __future__ import annotations

from typing import Any

import pytest

from netops.fake import FakeMerakiClient
from netops.models import NetworkConfig

NET = "N_test"


def make_config(**overrides: Any) -> NetworkConfig:
    data: dict[str, Any] = {
        "network": NET,
        "vlans": [
            {
                "id": 1,
                "name": "Default",
                "subnet": "192.168.128.0/24",
                "appliance_ip": "192.168.128.1",
            },
            {"id": 10, "name": "Corp", "subnet": "10.0.10.0/24", "appliance_ip": "10.0.10.1"},
        ],
        "firewall_l3": [
            {
                "comment": "guest to corp",
                "policy": "deny",
                "src_cidr": "10.0.20.0/24",
                "dest_cidr": "10.0.10.0/24",
            },
        ],
    }
    data.update(overrides)
    return NetworkConfig.model_validate(data)


@pytest.fixture
def client() -> FakeMerakiClient:
    return FakeMerakiClient()
