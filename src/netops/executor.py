"""Apply a plan: backup first, execute, then verify the network matches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netops.backup import save_backup, snapshot
from netops.client import MerakiClient
from netops.models import NetworkConfig
from netops.planner import Action, plan


class ApplyError(RuntimeError):
    """An action failed midway. The backup taken before the run is in ``backup``."""

    def __init__(self, message: str, backup: Path, done: list[Action]) -> None:
        super().__init__(message)
        self.backup = backup
        self.done = done


class VerificationError(RuntimeError):
    """Everything was sent, but re-reading the network still shows differences."""


@dataclass
class ApplyResult:
    backup: Path | None
    applied: list[Action]


def _execute(action: Action, network: str, client: MerakiClient) -> None:
    if action.resource == "vlan":
        vid = int(action.key)
        if action.op == "create":
            client.create_vlan(network, vid, action.after)
        elif action.op == "update":
            client.update_vlan(network, vid, {k: action.after[k] for k in action.changes})
        elif action.op == "delete":
            client.delete_vlan(network, vid)
    elif action.resource == "firewall_l3" and action.op == "replace":
        client.set_l3_rules(network, action.after)
    else:  # pragma: no cover - guarded by the planner's types
        raise ValueError(f"unsupported action {action}")


def apply(
    config: NetworkConfig,
    client: MerakiClient,
    actions: list[Action],
    *,
    backup_dir: Path,
    prune: bool = False,
) -> ApplyResult:
    if not actions:
        return ApplyResult(backup=None, applied=[])

    backup = save_backup(snapshot(client, config.network), backup_dir)

    done: list[Action] = []
    for action in actions:
        try:
            _execute(action, config.network, client)
        except Exception as exc:
            raise ApplyError(
                f"{action.op} {action.resource} {action.key} failed: {exc}", backup, done
            ) from exc
        done.append(action)

    leftover = plan(config, client, prune=prune)
    if leftover:
        keys = ", ".join(f"{a.op} {a.resource} {a.key}" for a in leftover)
        raise VerificationError(f"network still differs after apply: {keys}")

    return ApplyResult(backup=backup, applied=done)
