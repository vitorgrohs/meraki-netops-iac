"""Command line: validate, plan, apply, backup, rollback."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape

from netops.backup import load_backup, save_backup, snapshot, snapshot_to_config
from netops.client import DashboardClient, MerakiClient
from netops.executor import ApplyError, VerificationError, apply
from netops.fake import FakeMerakiClient
from netops.models import NetworkConfig, load_configs
from netops.planner import Action, PlanError, plan

app = typer.Typer(
    help="Cisco Meraki network configuration as code.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(highlight=False)

SIM_STATE = Path(".netops-sim.json")

Simulate = Annotated[
    bool, typer.Option("--simulate", help="Use the in-memory fake API (no Meraki account).")
]
BackupDir = Annotated[Path, typer.Option("--backup-dir", help="Where backups are written.")]
Prune = Annotated[bool, typer.Option("--prune", help="Also delete VLANs missing from YAML.")]
Fmt = Annotated[str, typer.Option("--format", help="text or markdown (for PR comments).")]


def _client(simulate: bool) -> MerakiClient:
    if simulate:
        return FakeMerakiClient(state_file=SIM_STATE)
    try:
        return DashboardClient()
    except RuntimeError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(1) from exc


def _load(path: Path) -> list[tuple[Path, NetworkConfig]]:
    try:
        return load_configs(path)
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        console.print(f"[red]invalid configuration:[/] {exc}")
        raise typer.Exit(1) from exc


def _fmt(value: Any) -> str:
    return f"'{value}'" if isinstance(value, str) else str(value)


def _rule(r: dict[str, Any]) -> str:
    """One-line view of a firewall rule: policy proto src[:port] -> dst[:port]  # comment."""

    def end(cidr: str, port: str) -> str:
        return cidr if port == "Any" else f"{cidr}:{port}"

    src = end(r["srcCidr"], r["srcPort"])
    dst = end(r["destCidr"], r["destPort"])
    return f"{r['policy']:5} {r['protocol']:4} {src} -> {dst}  # {r['comment']}"


def render(network: str, actions: list[Action], fmt: str = "text") -> str:
    """Human-readable plan. ``markdown`` wraps it in a diff block for PR comments."""
    lines: list[str] = []
    for a in actions:
        if a.resource == "vlan" and a.op == "create":
            lines.append(f"+ vlan {a.key}  {a.after['name']}  {a.after['subnet']}")
        elif a.resource == "vlan" and a.op == "update":
            lines.append(f"~ vlan {a.key}")
            lines += [
                f"~     {k}: {_fmt(old)} -> {_fmt(new)}" for k, (old, new) in a.changes.items()
            ]
        elif a.resource == "vlan" and a.op == "delete":
            lines.append(f"- vlan {a.key}  {a.before['name']}  {a.before['subnet']}")
        elif a.resource == "firewall_l3":
            lines.append(f"~ firewall_l3: {len(a.before)} -> {len(a.after)} rules")
            lines += [f"-     {_rule(r)}" for r in a.before]
            lines += [f"+     {_rule(r)}" for r in a.after]
    summary = f"{network}: no changes" if not actions else f"{network}: {len(actions)} change(s)"
    if fmt == "markdown":
        body = "\n".join(lines)
        return f"**{summary}**\n" + (f"```diff\n{body}\n```\n" if lines else "")
    return "\n".join([summary, *lines])


def _print(text: str) -> None:
    for line in text.splitlines():
        color = {"+": "green", "-": "red", "~": "yellow"}.get(line[:1])
        console.print(f"[{color}]{escape(line)}[/]" if color else line, markup=bool(color))


@app.command()
def validate(path: Path) -> None:
    """Validate YAML files without calling the API."""
    configs = _load(path)
    for file, cfg in configs:
        rules = "unmanaged" if cfg.firewall_l3 is None else len(cfg.firewall_l3)
        console.print(
            f"[green]ok[/] {file.name}: {cfg.network}, "
            f"{len(cfg.vlans)} VLAN(s), firewall rules: {rules}"
        )


@app.command("plan")
def plan_cmd(
    path: Path, simulate: Simulate = False, prune: Prune = False, fmt: Fmt = "text"
) -> None:
    """Show what would change. Never modifies anything."""
    client = _client(simulate)
    for _, cfg in _load(path):
        try:
            actions = plan(cfg, client, prune=prune)
        except PlanError as exc:
            console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(1) from exc
        out = render(cfg.network, actions, fmt)
        typer.echo(out) if fmt == "markdown" else _print(out)


@app.command("apply")
def apply_cmd(
    path: Path,
    simulate: Simulate = False,
    prune: Prune = False,
    backup_dir: BackupDir = Path("backups"),
    yes: Annotated[
        bool, typer.Option("--yes", help="Actually apply (otherwise plan only).")
    ] = False,
) -> None:
    """Apply the changes. Takes a backup first and verifies the result."""
    client = _client(simulate)
    for _, cfg in _load(path):
        _run(cfg, client, prune=prune, backup_dir=backup_dir, yes=yes)


def _run(
    cfg: NetworkConfig, client: MerakiClient, *, prune: bool, backup_dir: Path, yes: bool
) -> None:
    try:
        actions = plan(cfg, client, prune=prune)
    except PlanError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    _print(render(cfg.network, actions))
    if not actions:
        return
    if not yes:
        console.print("[dim]dry run - re-run with --yes to apply[/]")
        return
    try:
        result = apply(cfg, client, actions, backup_dir=backup_dir, prune=prune)
    except ApplyError as exc:
        console.print(f"[red]apply failed:[/] {exc}")
        console.print(f"backup taken before the run: {exc.backup}")
        console.print(f"to undo what was done: netops rollback {cfg.network} {exc.backup} --yes")
        raise typer.Exit(1) from exc
    except VerificationError as exc:
        console.print(f"[red]verification failed:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]applied {len(result.applied)} change(s)[/] - backup: {result.backup}")


@app.command("backup")
def backup_cmd(
    network: str, simulate: Simulate = False, backup_dir: BackupDir = Path("backups")
) -> None:
    """Save the current VLANs and firewall rules of a network."""
    path = save_backup(snapshot(_client(simulate), network), backup_dir)
    console.print(f"[green]saved[/] {path}")


@app.command()
def rollback(
    network: str,
    backup_file: Path,
    simulate: Simulate = False,
    backup_dir: BackupDir = Path("backups"),
    yes: Annotated[bool, typer.Option("--yes", help="Actually restore.")] = False,
) -> None:
    """Restore a backup (VLANs not in the backup are removed)."""
    snap = load_backup(backup_file)
    if snap["network"] != network:
        console.print(f"[red]error:[/] backup belongs to {snap['network']}, not {network}")
        raise typer.Exit(1)
    _run(snapshot_to_config(snap), _client(simulate), prune=True, backup_dir=backup_dir, yes=yes)


if __name__ == "__main__":  # pragma: no cover
    app()
