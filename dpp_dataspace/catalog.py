"""DCP-style catalog of dataset offers with DPP filter and paging support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import crypto
from .identity import Participant
from .policy import Policy


@dataclass
class Offer:
    """A dataset offer published in a provider catalog."""

    offer_id: str
    provider_did: str
    dataset_id: str
    asset_id: str
    asset_type: str
    title: str
    description: str
    policy: Policy
    dpp_hash: str
    contract_definition_id: str
    created_at: int = field(default_factory=crypto.now_epoch)


class CatalogService:
    """In-process catalog service for a single provider participant."""

    def __init__(self, provider: Participant, ledger) -> None:
        self.provider = provider
        self.ledger = ledger
        self._offers: Dict[str, Offer] = {}

    def publish_passport_offer(
        self,
        asset_id: str,
        title: str,
        description: str,
        policy: Policy,
        dpp_hash: str,
    ) -> Offer:
        dataset_id = f"dataset:{asset_id}:dpp"
        contract_definition_id = f"cd:{asset_id}"
        offer_id = f"offer:{asset_id}:{crypto.content_hash(title.encode())[:8]}"
        if offer_id in self._offers:
            raise ValueError(f"duplicate offer: {offer_id}")
        offer = Offer(
            offer_id=offer_id,
            provider_did=self.provider.did,
            dataset_id=dataset_id,
            asset_id=asset_id,
            asset_type="dpp:building-component",
            title=title,
            description=description,
            policy=policy,
            dpp_hash=dpp_hash,
            contract_definition_id=contract_definition_id,
        )
        self._offers[offer_id] = offer
        self.ledger.append(
            "catalog.offer.published",
            self.provider.did,
            {"offerId": offer_id, "assetId": asset_id, "dppHash": offer.dpp_hash},
        )
        return offer

    def get(self, offer_id: str) -> Optional[Offer]:
        return self._offers.get(offer_id)

    def require(self, offer_id: str) -> Offer:
        offer = self._offers.get(offer_id)
        if offer is None:
            raise LookupError(f"unknown offer: {offer_id}")
        return offer

    def require_by_asset(self, asset_id: str) -> str:
        for offer in self._offers.values():
            if offer.asset_id == asset_id:
                return offer.offer_id
        raise LookupError(f"no offer for asset: {asset_id}")

    def search(
        self,
        query: Optional[str] = None,
        asset_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Dict[str, Any]:
        matches = [
            o
            for o in self._offers.values()
            if (asset_type is None or o.asset_type == asset_type)
            and (
                query is None
                or query.lower() in o.title.lower()
                or query.lower() in o.description.lower()
            )
        ]
        matches.sort(key=lambda o: o.created_at)
        start = (page - 1) * page_size
        chunk = matches[start : start + page_size]
        return {
            "datasets": [
                {
                    "offerId": o.offer_id,
                    "datasetId": o.dataset_id,
                    "assetId": o.asset_id,
                    "assetType": o.asset_type,
                    "title": o.title,
                    "description": o.description,
                    "policy": o.policy.as_dict(),
                    "provider": o.provider_did,
                    "dppHash": o.dpp_hash,
                    "contractDefinitionId": o.contract_definition_id,
                }
                for o in chunk
            ],
            "total": len(matches),
            "page": page,
            "pageSize": page_size,
        }

    def stats(self) -> Dict[str, int]:
        return {"offers": len(self._offers)}
