"""Participant identity and signed VerifiableCredential-style membership.

Kept close to dataspace semantics: every participant has a DID, a set of
attributes (e.g. ``dataSpaceMembership``, ``legalName``), and the federation
authority issues an signed membership credential that other participants can
verify before negotiating contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import crypto

FEDERATION_AUTHORITY = "did:web:federation.buildingmaterials.example"


@dataclass
class Participant:
    did: str
    display_name: str
    roles: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    membership_credential: Optional[Dict[str, Any]] = None

    def request_membership(self) -> Dict[str, Any]:
        credential = {
            "@context": ["https://www.w3.org/ns/credentials/v2"],
            "type": ["VerifiableCredential", "DataspaceMembershipCredential"],
            "issuer": FEDERATION_AUTHORITY,
            "credentialSubject": {
                "id": self.did,
                "displayName": self.display_name,
                "roles": sorted(self.roles),
                "attributes": dict(self.attributes),
            },
            "issuanceDate": crypto.now_epoch(),
        }
        self.membership_credential = crypto.sign_document(
            FEDERATION_AUTHORITY, credential
        )
        return self.membership_credential

    def public_profile(self) -> Dict[str, Any]:
        return {
            "did": self.did,
            "displayName": self.display_name,
            "roles": list(self.roles),
            "attributes": dict(self.attributes),
        }


class ParticipantDirectory:
    """The federation's membership registry."""

    def __init__(self) -> None:
        self._participants: Dict[str, Participant] = {}

    def register(self, participant: Participant) -> Dict[str, Any]:
        if participant.did in self._participants:
            raise ValueError(f"duplicate DID: {participant.did}")
        self._participants[participant.did] = participant
        return participant.request_membership()

    def get(self, did: str) -> Optional[Participant]:
        return self._participants.get(did)

    def require(self, did: str) -> Participant:
        participant = self._participants.get(did)
        if participant is None:
            raise LookupError(f"unknown participant DID: {did}")
        return participant

    def has_valid_membership(self, did: str) -> bool:
        participant = self._participants.get(did)
        if participant is None or participant.membership_credential is None:
            return False
        return crypto.verify_document(
            FEDERATION_AUTHORITY, participant.membership_credential
        )

    def all_participants(self) -> List[Participant]:
        return list(self._participants.values())
