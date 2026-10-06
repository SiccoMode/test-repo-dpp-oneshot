"""Consumer-side DPP resolution: fetch, verify and index passports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import crypto
from .contract import Agreement
from .identity import ParticipantDirectory
from .passport import DigitalProductPassport, verify_passport_document


@dataclass
class ResolvedPassport:
    asset_id: str
    document: Dict[str, Any]
    fingerprint: str
    verified: bool
    fetched_at: int
    agreement_id: str
    raw_sha256: str


class PassportResolver:
    """Fetches DPPs through the transfer plane and verifies them."""

    def __init__(self, consumer_did: str, directory: ParticipantDirectory, ledger) -> None:
        self.consumer_did = consumer_did
        self.directory = directory
        self.ledger = ledger
        self.cache: Dict[str, ResolvedPassport] = {}

    def resolve(
        self,
        endpoint: str,
        agreement: Agreement,
        asset_id: str,
        *,
        expected_hash: Optional[str] = None,
    ) -> ResolvedPassport:
        from .transfer import http_pull

        status, body = http_pull(endpoint, self.consumer_did, agreement.agreement_id, asset_id)
        if status != 200:
            raise RuntimeError(f"pull failed with HTTP {status}: {body.decode(errors='replace')}")
        resolved = self.verify(asset_id, body, agreement.agreement_id, expected_hash)
        self.cache[asset_id] = resolved
        return resolved

    def verify(
        self,
        asset_id: str,
        body: bytes,
        agreement_id: str,
        expected_hash: Optional[str] = None,
    ) -> ResolvedPassport:
        try:
            document = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"artifact is not valid JSON: {exc}") from exc
        manufacturer_did = document.get("identification", {}).get("manufacturer", "")
        verified = verify_passport_document(manufacturer_did, document)
        recomputed = crypto.content_hash(crypto.canonical_json(document).encode())
        if expected_hash is not None and expected_hash != recomputed:
            raise RuntimeError(
                f"dpp hash mismatch for {asset_id}: expected {expected_hash}, got {recomputed}"
            )
        fingerprint = recomputed
        resolved = ResolvedPassport(
            asset_id=asset_id,
            document=document,
            fingerprint=fingerprint,
            verified=verified,
            fetched_at=crypto.now_epoch(),
            agreement_id=agreement_id,
            raw_sha256=crypto.content_hash(body),
        )
        if not verified:
            self.ledger.append(
                "dpp.verification.failed",
                self.consumer_did,
                {"assetId": asset_id, "claimedManufacturer": manufacturer_did},
            )
        return resolved

    def verify_signature_against(
        self, resolved: ResolvedPassport, manufacturer_did: str
    ) -> bool:
        return verify_passport_document(manufacturer_did, resolved.document)


@dataclass
class ProjectDppIndex:
    """A construction project's view over the passports it has consumed."""

    project_id: str
    entries: List[ResolvedPassport] = field(default_factory=list)

    def add(self, resolved: ResolvedPassport) -> None:
        self.entries.append(resolved)

    def total_gwp(self) -> float:
        return sum(
            float(e.document.get("sustainability", {}).get("gwpTotal") or 0.0)
            for e in self.entries
        )

    def recalled(self) -> List[ResolvedPassport]:
        return [e for e in self.entries if e.document.get("status") == "recalled"]

    def unverified(self) -> List[ResolvedPassport]:
        return [e for e in self.entries if not e.verified]

    def materials(self) -> List[str]:
        out: List[str] = []
        for entry in self.entries:
            name = entry.document.get("identification", {}).get("name")
            if name and name not in out:
                out.append(name)
        return out

    def summary(self) -> Dict[str, Any]:
        return {
            "projectId": self.project_id,
            "passports": len(self.entries),
            "materials": self.materials(),
            "totalGwp": round(self.total_gwp(), 2),
            "recalledCount": len(self.recalled()),
            "unverifiedCount": len(self.unverified()),
        }
