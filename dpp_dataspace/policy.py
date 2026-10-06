"""Dataspace policy evaluation for contract offers.

Policies are the ``odrl:permission`` / ``odrl:prohibition`` style constraint
sets that DPP data providers attach to their catalog offers. The engine here
implements the subset of the Dataspace Protocol profile that the testbed
exercises: role requirements, jurisdiction constraints and purpose binding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .identity import Participant, ParticipantDirectory

INHERITED_MEMBERSHIP = "dsr:inheritedMembership"


@dataclass
class Constraint:
    left: str
    operator: str
    right: List[str]

    def evaluate(self, attributes: Dict[str, Any]) -> bool:
        actual = attributes.get(self.left)
        if actual is None:
            return False
        actual_values = actual if isinstance(actual, list) else [actual]
        if self.operator == "isAnyOf":
            return bool(set(actual_values) & set(self.right))
        if self.operator == "isAllOf":
            return set(self.right).issubset(set(actual_values))
        if self.operator == "isNoneOf":
            return not (set(actual_values) & set(self.right))
        raise ValueError(f"unsupported constraint operator: {self.operator}")

    def as_dict(self) -> Dict[str, Any]:
        return {"left": self.left, "operator": self.operator, "right": list(self.right)}


@dataclass
class Policy:
    """An ``odrl:Offer``: permissions plus prohibitions."""

    permissions: List[Constraint] = field(default_factory=list)
    prohibitions: List[Constraint] = field(default_factory=list)
    duty_ids: List[str] = field(default_factory=list)

    def evaluate(self, consumer: Participant) -> Dict[str, Any]:
        attributes = dict(consumer.attributes)
        attributes.setdefault("roles", consumer.roles)
        attributes["memberOfDataspace"] = "true"
        for constraint in self.permissions:
            if not constraint.evaluate(attributes):
                return {
                    "allowed": False,
                    "reason": f"permission not satisfied: {constraint.left} "
                    f"{constraint.operator} {constraint.right}",
                }
        for constraint in self.prohibitions:
            if constraint.evaluate(attributes):
                return {
                    "allowed": False,
                    "reason": f"prohibition triggered: {constraint.left} "
                    f"{constraint.operator} {constraint.right}",
                }
        return {"allowed": True, "reason": "all permissions satisfied"}

    def as_dict(self) -> Dict[str, Any]:
        return {
            "permissions": [c.as_dict() for c in self.permissions],
            "prohibitions": [c.as_dict() for c in self.prohibitions],
            "duties": list(self.duty_ids),
        }


def membership_only_policy() -> Policy:
    return Policy(permissions=[Constraint("memberOfDataspace", "isAnyOf", ["true"])])


def role_policy(roles: List[str]) -> Policy:
    return Policy(permissions=[Constraint("roles", "isAnyOf", list(roles))])


def evaluate_consumer(policy: Policy, directory: ParticipantDirectory, did: str):
    consumer = directory.require(did)
    return policy.evaluate(consumer), consumer
