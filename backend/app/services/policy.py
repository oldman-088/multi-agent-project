"""Action policy: ordered allow | ask | deny rules, first match wins (SPEC §13.2).

The policy is stored per organization and per autonomy level. Defaults follow the
specification: full-auto allows everything inside the sandbox, but ships a short
``ask`` list for irreversible actions that leave it.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Sequence
from typing import Any

from backend.app.core.errors import ValidationFailedError
from backend.app.models.enums import AutonomyLevel, PolicyDecision
from backend.app.schemas.connections import PolicyEvaluateRequest, PolicyRuleIn

#: Irreversible actions that leave the sandbox: the Level 3 default ``ask`` list.
DEFAULT_ASK_RULES: list[dict[str, Any]] = [
    {"decision": "ask", "tool": "git.force_push", "reason": "force-push to a protected branch"},
    {
        "decision": "ask",
        "tool": "fs.delete_outside_workspace",
        "reason": "delete outside workspace",
    },
    {"decision": "ask", "tool": "payments.charge", "reason": "payments cannot be undone"},
    {"decision": "ask", "tool": "messages.send_external", "reason": "sending external messages"},
]

#: Manual/assisted levels ask for every tool call (SPEC §13.1).
STRICT_LEVELS = {AutonomyLevel.MANUAL, AutonomyLevel.ASSISTED}
#: Autopilot asks only for irreversible calls; full-auto allows all inside sandbox.
PERMISSIVE_LEVELS = {AutonomyLevel.AUTOPILOT, AutonomyLevel.FULL_AUTO}


def default_policy(level: AutonomyLevel) -> list[dict[str, Any]]:
    """Built-in policy for a level when the owner has not customised one.

    The irreversible ``ask`` rules stay ahead of the catch-all at every level, so
    a force-push or a payment always asks even in full-auto (SPEC §13.2).
    """
    if level in STRICT_LEVELS:
        return [
            {
                "decision": "ask",
                "match_all": True,
                "reason": f"level {level.value} asks for every tool call",
            }
        ]
    if level is AutonomyLevel.AUTOPILOT:
        return [
            *DEFAULT_ASK_RULES,
            {"decision": "allow", "match_all": True, "reason": "level 2 default allow"},
        ]
    return [
        *DEFAULT_ASK_RULES,
        {
            "decision": "allow",
            "match_all": True,
            "reason": "level 3 allows everything inside the sandbox",
        },
    ]


def validate_rules(
    rules: Sequence[PolicyRuleIn | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate and normalise policy rules; reject inert or malformed rules."""
    normalised: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        data = rule.model_dump() if isinstance(rule, PolicyRuleIn) else dict(rule)
        decision = data.get("decision")
        if decision not in {d.value for d in PolicyDecision}:
            raise ValidationFailedError(
                f"Rule {index} has invalid decision '{decision}'",
                code="invalid_policy_rule",
            )
        matchers = {
            key: data.get(key)
            for key in ("tool", "path_glob", "host", "command_pattern", "agent_id")
        }
        match_all = bool(data.get("match_all"))
        if not any(matchers.values()) and not match_all:
            raise ValidationFailedError(
                f"Rule {index} has no matcher; set match_all explicitly for a catch-all",
                code="invalid_policy_rule",
                details={"index": index},
            )
        if data.get("command_pattern"):
            try:
                re.compile(data["command_pattern"])
            except re.error as exc:
                raise ValidationFailedError(
                    f"Rule {index} has an invalid command_pattern: {exc}",
                    code="invalid_policy_rule",
                ) from exc
        normalised.append(
            {
                "decision": decision,
                "match_all": match_all,
                "tool": matchers["tool"],
                "path_glob": matchers["path_glob"],
                "host": matchers["host"],
                "command_pattern": matchers["command_pattern"],
                "agent_id": matchers["agent_id"],
            }
        )
    return normalised


def _matches(rule: dict[str, Any], request: PolicyEvaluateRequest) -> bool:
    """A rule matches when every matcher it declares matches the request."""
    if rule.get("match_all"):
        return True
    compared = False
    if rule.get("tool"):
        if not request.tool or not fnmatch.fnmatch(request.tool, str(rule["tool"])):
            return False
        compared = True
    if rule.get("path_glob"):
        if not request.path or not fnmatch.fnmatch(request.path, str(rule["path_glob"])):
            return False
        compared = True
    if rule.get("host"):
        if not request.host or not fnmatch.fnmatch(request.host, str(rule["host"])):
            return False
        compared = True
    if rule.get("agent_id"):
        if not request.agent_id or request.agent_id != rule["agent_id"]:
            return False
        compared = True
    if rule.get("command_pattern"):
        if not request.command or not re.search(str(rule["command_pattern"]), request.command):
            return False
        compared = True
    return compared


def evaluate(
    rules: list[dict[str, Any]], request: PolicyEvaluateRequest
) -> tuple[PolicyDecision, int | None, str]:
    """Return ``(decision, matched_rule_index, reason)``. First match wins."""
    for index, rule in enumerate(rules):
        if _matches(rule, request):
            return (
                PolicyDecision(rule["decision"]),
                index,
                str(rule.get("reason") or f"matched rule {index}"),
            )
    # Default when nothing matches is the safe choice, not "allow".
    return PolicyDecision.ASK, None, "no rule matched; default is to ask the owner"


def is_irreversible_leaving_sandbox(tool: str) -> bool:
    return any(fnmatch.fnmatch(tool, str(rule["tool"])) for rule in DEFAULT_ASK_RULES)
