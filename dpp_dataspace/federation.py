"""Federation wiring: one call sets up a working DPP dataspace testbed."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import crypto
from .catalog import CatalogService
from .contract import ContractNegotiationService
from .identity import Participant, ParticipantDirectory
from .ledger import EventLedger
from .passport import DigitalProductPassport, build_demo_passport
from .policy import Policy, membership_only_policy, role_policy
from .resolver import PassportResolver, ProjectDppIndex
from .transfer import ArtifactStore, LoopbackProviderServer, TransferService


class BuildingMaterialsDataspace:
    """A complete in-process dataspace instance for the testbed."""

    def __init__(self, name: str = "building-materials-dataspace") -> None:
        self.name = name
        self.ledger = EventLedger()
        self.directory = ParticipantDirectory()
        self.providers: Dict[str, Dict[str, object]] = {}

    # -- membership ----------------------------------------------------------
    def join(self, did: str, display_name: str, roles: List[str],
             attributes: Optional[Dict] = None) -> Participant:
        participant = Participant(
            did=did,
            display_name=display_name,
            roles=list(roles),
            attributes=dict(attributes or {}),
        )
        self.directory.register(participant)
        self.ledger.append(
            "participant.joined",
            did,
            {"displayName": display_name, "roles": sorted(roles)},
        )
        return participant

    # -- provider-side -------------------------------------------------------
    def register_provider(
        self,
        provider_did: str,
        display_name: str,
        roles: Optional[List[str]] = None,
    ) -> Tuple[Participant, CatalogService, ContractNegotiationService,
               ArtifactStore, TransferService]:
        provider = self.join(provider_did, display_name, roles or ["provider"])
        catalog = CatalogService(provider, self.ledger)
        negotiations = ContractNegotiationService(
            provider_did, catalog, self.directory, self.ledger
        )
        store = ArtifactStore()
        transfer = TransferService(
            provider_did, store, negotiations, self.directory, self.ledger
        )
        self.providers[provider_did] = {
            "participant": provider,
            "catalog": catalog,
            "negotiations": negotiations,
            "store": store,
            "transfer": transfer,
        }
        return provider, catalog, negotiations, store, transfer

    def publish_dpp(
        self,
        provider_did: str,
        passport: DigitalProductPassport,
        title: str,
        description: str,
        policy: Optional[Policy] = None,
    ) -> str:
        """Store the signed DPP artifact and publish a catalog offer."""
        entry = self.providers[provider_did]
        catalog: CatalogService = entry["catalog"]
        store: ArtifactStore = entry["store"]
        import json

        signed = passport.signed_copy()
        payload = json.dumps(signed).encode()
        dpp_hash = crypto.content_hash(crypto.canonical_json(signed).encode())
        store.put(passport.passport_id, payload)
        offer = catalog.publish_passport_offer(
            asset_id=passport.passport_id,
            title=title,
            description=description,
            policy=policy or membership_only_policy(),
            dpp_hash=dpp_hash,
        )
        return offer.offer_id

    # -- consumer-side ---------------------------------------------------------
    def consumer_resolver(self, consumer_did: str) -> PassportResolver:
        return PassportResolver(consumer_did, self.directory, self.ledger)

    def negotiate(self, provider_did: str, consumer_did: str, offer_id: str):
        entry = self.providers[provider_did]
        negotiations: ContractNegotiationService = entry["negotiations"]
        result = negotiations.initiate(consumer_did, offer_id)
        return negotiations.agree(result["negotiationId"])

    def transfer_service(self, provider_did: str) -> TransferService:
        return self.providers[provider_did]["transfer"]

    def catalog_of(self, provider_did: str) -> CatalogService:
        return self.providers[provider_did]["catalog"]

    # -- audit ---------------------------------------------------------------
    def audit_summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.ledger.entries():
            counts[entry.event_type] = counts.get(entry.event_type, 0) + 1
        return counts


def create_testbed() -> BuildingMaterialsDataspace:
    """The demo scenario: two producers, one recycler, one project consumer."""
    ds = BuildingMaterialsDataspace()

    concrete = ds.register_provider(
        "did:web:precast.example", "Nordrhein Precast GmbH", ["provider"]
    )
    ds.register_provider(
        "did:web:steel.example", "Ruhr Stahlwerke AG", ["provider"]
    )

    recycler = ds.join(
        "did:web:recycler.example",
        "BauCycle Recycling eG",
        ["consumer", "recycler"],
        {"jurisdiction": "DE", "purposes": ["end-of-life-processing"]},
    )

    project = ds.join(
        "did:web:project.example",
        "K&G Bauunternehmen (project BlueTower)",
        ["consumer"],
        {"jurisdiction": "DE", "purposes": ["construction-project-data-integration"]},
    )

    p1 = build_demo_passport("dpp:precast:PE-2024-0001", "did:web:precast.example")
    p2 = build_demo_passport(
        "dpp:precast:PE-2024-0002", "did:web:precast.example",
        name="Precast concrete slab", gwp=180.0,
    )
    p3 = build_demo_passport(
        "dpp:steel:SB-2024-0007", "did:web:steel.example",
        name="Structural steel beam S355", gwp=1.9,
    )

    ds.publish_dpp(
        "did:web:precast.example", p1,
        "Precast wall element DPP",
        "Digital Product Passport for precast concrete wall element incl. EPD and DoP",
        policy=role_policy(["consumer", "recycler"]),
    )
    ds.publish_dpp(
        "did:web:precast.example", p2,
        "Precast slab DPP",
        "Digital Product Passport for precast concrete floor slab",
        policy=membership_only_policy(),
    )
    ds.publish_dpp(
        "did:web:steel.example", p3,
        "Steel beam DPP",
        "Digital Product Passport for hot-rolled structural steel beam",
        policy=membership_only_policy(),
    )

    return ds


def run_demo_scenario() -> Dict[str, object]:
    """End-to-end happy-path exchange, used by tests and the CLI demo."""
    ds = create_testbed()
    project_resolver = ds.consumer_resolver("did:web:project.example")

    with LoopbackProviderServer(ds.transfer_service("did:web:precast.example")) as server:
        catalog_page = ds.catalog_of("did:web:precast.example").search("Precast")
        results = []
        for dataset in catalog_page["datasets"]:
            agreement = ds.negotiate(
                "did:web:precast.example",
                "did:web:project.example",
                dataset["offerId"],
            )
            resolved = project_resolver.resolve(server.endpoint, agreement, dataset["assetId"])
            results.append(resolved)

    index = ProjectDppIndex(project_id="BlueTower")
    for resolved in results:
        index.add(resolved)

    return {
        "dataspace": ds,
        "index": index,
        "resolved": results,
        "audit": ds.audit_summary(),
        "chainValid": ds.ledger.verify_chain(),
    }
