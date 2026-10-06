"""EDC-style contract negotiation and agreement registry.

Implements the Dataspace Protocol negotiation state machine
(offer -> request -> agreement) with policy enforcement at contract
definition time, and keeps signed agreements for transfer authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import crypto
from .catalog import CatalogService
from .identity import ParticipantDirectory
from .policy import Policy

NEGOTIATION_STATES = ("REQUESTED", "AGREED", "DECLINED", "TERMINATED")
ACTION_USE = "use"


class PolicyDenied(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NegotiationError(Exception):
    pass


@dataclass
class Agreement:
    agreement_id: str
    contract_definition_id: str
    provider_did: str
    consumer_did: str
    offer_id: str
    asset_id: str
    policy: Policy
    signature: str
    created_at: int
    revoked: bool = False


class ContractNegotiationService:
    def __init__(
        self,
        provider_did: str,
        catalog: CatalogService,
        directory: ParticipantDirectory,
        ledger,
    ) -> None:
        self.provider_did = provider_did
        self.catalog = catalog
        self.directory = directory
        self.ledger = ledger
        self._negotiations: Dict[str, Dict[str, Any]] = {}
        self._agreements: Dict[str, Agreement] = {}

    # -- negotiation ---------------------------------------------------------
    def initiate(
        self,
        consumer_did: str,
        offer_id: str,
        purpose: str = "construction-project-data-integration",
    ) -> Dict[str, Any]:
        offer = self.catalog.require(offer_id)
        if not self.directory.has_valid_membership(consumer_did):
            raise NegotiationError(
                f"consumer {consumer_did} has no valid dataspace membership"
            )
        evaluation = offer.policy.evaluate(self.directory.require(consumer_did))
        if not evaluation["allowed"]:
            self.ledger.append(
                "negotiation.declined",
                self.provider_did,
                {"offerId": offer_id, "consumer": consumer_did, "reason": evaluation["reason"]},
            )
            raise PolicyDenied(evaluation["reason"])
        negotiation_id = f"neg:{crypto.content_hash(f'{consumer_did}{offer_id}'.encode())[:12]}"
        self._negotiations[negotiation_id] = {
            "state": "REQUESTED",
            "consumer": consumer_did,
            "offer": offer,
            "purpose": purpose,
        }
        self.ledger.append(
            "negotiation.requested",
            consumer_did,
            {"negotiationId": negotiation_id, "offerId": offer_id},
        )
        return {
            "negotiationId": negotiation_id,
            "state": "REQUESTED",
            "offer": offer.offer_id,
        }

    def agree(self, negotiation_id: str) -> Agreement:
        negotiation = self._negotiations.get(negotiation_id)
        if negotiation is None:
            raise NegotiationError(f"unknown negotiation: {negotiation_id}")
        if negotiation["state"] != "REQUESTED":
            raise NegotiationError(
                f"negotiation {negotiation_id} in state {negotiation['state']}"
            )
        offer = negotiation["offer"]
        agreement_id = f"agr:{crypto.content_hash(negotiation_id.encode())[:16]}"
        agreement = Agreement(
            agreement_id=agreement_id,
            contract_definition_id=offer.contract_definition_id,
            provider_did=self.provider_did,
            consumer_did=negotiation["consumer"],
            offer_id=offer.offer_id,
            asset_id=offer.asset_id,
            policy=offer.policy,
            signature=crypto.sign(
                self.provider_did,
                f"{agreement_id}|{offer.asset_id}|{negotiation['consumer']}".encode(),
            ),
            created_at=crypto.now_epoch(),
        )
        self._agreements[agreement_id] = agreement
        negotiation["state"] = "AGREED"
        self.ledger.append(
            "agreement.created",
            self.provider_did,
            {"agreementId": agreement_id, "assetId": offer.asset_id,
             "consumer": agreement.consumer_did},
        )
        return agreement

    def decline(self, negotiation_id: str, reason: str = "not acceptable") -> None:
        negotiation = self._negotiations.get(negotiation_id)
        if negotiation is None:
            raise NegotiationError(f"unknown negotiation: {negotiation_id}")
        negotiation["state"] = "DECLINED"
        self.ledger.append(
            "negotiation.declined",
            self.provider_did,
            {"negotiationId": negotiation_id, "reason": reason},
        )

    # -- agreements ----------------------------------------------------------
    def get_agreement(self, agreement_id: str) -> Optional[Agreement]:
        return self._agreements.get(agreement_id)

    def verify_agreement(self, agreement_id: str) -> bool:
        agreement = self._agreements.get(agreement_id)
        if agreement is None or agreement.revoked:
            return False
        payload = (
            f"{agreement.agreement_id}|{agreement.asset_id}|{agreement.consumer_did}"
        ).encode()
        return crypto.verify(agreement.provider_did, payload, agreement.signature)

    def terminate(self, agreement_id: str, by_did: str) -> None:
        agreement = self._agreements.get(agreement_id)
        if agreement is None:
            raise NegotiationError(f"unknown agreement: {agreement_id}")
        if by_did not in (agreement.provider_did, agreement.consumer_did):
            raise NegotiationError("not a party to the agreement")
        agreement.revoked = True
        self.ledger.append(
            "agreement.terminated",
            by_did,
            {"agreementId": agreement_id},
        )

    def consumer_agreements(self, consumer_did: str):
        return [a for a in self._agreements.values() if a.consumer_did == consumer_did]
