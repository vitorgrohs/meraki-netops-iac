from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from netops.cli import app

runner = CliRunner()
EXAMPLE = Path("networks/filial-exemplo.yaml").resolve()


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copy(EXAMPLE, tmp_path / "net.yaml")
    monkeypatch.chdir(tmp_path)  # isolates .netops-sim.json and backups/
    return tmp_path


def test_validate(workdir: Path) -> None:
    result = runner.invoke(app, ["validate", "net.yaml"])
    assert result.exit_code == 0, result.output
    assert "4 VLAN(s)" in result.output


def test_full_cycle_simulated(workdir: Path) -> None:
    plan = runner.invoke(app, ["plan", "net.yaml", "--simulate"])
    assert plan.exit_code == 0, plan.output
    assert "+ vlan 10" in plan.output

    dry = runner.invoke(app, ["apply", "net.yaml", "--simulate"])
    assert "dry run" in dry.output
    assert not (workdir / "backups").exists()

    done = runner.invoke(app, ["apply", "net.yaml", "--simulate", "--yes"])
    assert done.exit_code == 0, done.output
    assert "applied 4 change(s)" in done.output

    again = runner.invoke(app, ["plan", "net.yaml", "--simulate"])
    assert "no changes" in again.output

    backup = next((workdir / "backups").rglob("*.json"))
    undo = runner.invoke(
        app, ["rollback", "N_000000000000000001", str(backup), "--simulate", "--yes"]
    )
    assert undo.exit_code == 0, undo.output
    assert "- vlan 10" in undo.output


def test_markdown_plan_for_pull_requests(workdir: Path) -> None:
    result = runner.invoke(app, ["plan", "net.yaml", "--simulate", "--format", "markdown"])
    assert result.exit_code == 0, result.output
    assert "```diff" in result.output


def test_invalid_yaml_exits_1(workdir: Path) -> None:
    (workdir / "bad.yaml").write_text(
        "network: N_x\nvlans:\n  - {id: 5, name: a, subnet: 10.0.0.0/24, appliance_ip: 10.9.9.9}\n"
    )
    result = runner.invoke(app, ["validate", "bad.yaml"])
    assert result.exit_code == 1
    assert "outside" in result.output


def test_real_api_requires_key(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERAKI_API_KEY", raising=False)
    result = runner.invoke(app, ["plan", "net.yaml"])
    assert result.exit_code == 1
    assert "MERAKI_API_KEY" in result.output
