"""Digital Product Passport model for building materials and components.

The structure is aligned with the emerging CEN/CLC JTC 24 / EN 17665 style
DPP for construction products: identification, composition, sustainability,
circularity, performance and maintenance data, plus traceability events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import crypto

DPP_CONTEXT = [
    "https://www.w3.org/ns/credentials/v2",
    "https://testbed.buildingmaterials.example/dpp/v1",
]

PASSPORT_STATUSES = ("draft", "active", "recalled", "archived")


@dataclass
class TraceabilityEvent:
    timestamp: int
    actor_did: str
    event_type: str
    location: str
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "actor": self.actor_did,
            "eventType": self.event_type,
            "location": self.location,
            "details": dict(self.details),
        }


class DigitalProductPassport:
    """An in-memory DPP document with hash-anchored immutable sections."""

    def __init__(
        self,
        passport_id: str,
        material_passport_id: Optional[str] = None,
        *,
        name: str = "",
        gtin: str = "",
        product_group: str = "",
        manufacturer_did: str = "",
        production_site: str = "",
        manufacture_date: str = "",
        serial: str = "",
        status: str = "active",
    ) -> None:
        self.passport_id = passport_id
        self.material_passport_id = material_passport_id or f"mp:{passport_id}"
        self.name = name
        self.gtin = gtin
        self.product_group = product_group
        self.manufacturer_did = manufacturer_did
        self.production_site = production_site
        self.manufacture_date = manufacture_date
        self.serial = serial
        self.status = status
        self.composition: List[Dict[str, Any]] = []
        self.sustainability: Dict[str, Any] = {}
        self.circularity: Dict[str, Any] = {}
        self.performance: Dict[str, Any] = {}
        self.maintenance: Dict[str, Any] = {}
        self.traceability: List[TraceabilityEvent] = []
        self.attachments: Dict[str, str] = {}

    # -- mutable sections -------------------------------------------------
    def add_substance(self, name: str, mass_fraction: float, cas: str = "",
                      hazard: Optional[str] = None, recycled: bool = False) -> Dict[str, Any]:
        substance = {
            "name": name,
            "massFraction": mass_fraction,
            "cas": cas,
            "hazardClass": hazard,
            "recycledContent": recycled,
        }
        self.composition.append(substance)
        return substance

    def set_sustainability(self, gwp: Optional[float] = None, energy: Optional[float] = None,
                           water: Optional[float] = None, standard: str = "EN 15804+A2") -> None:
        self.sustainability = {
            "declaredUnit": "m3",
            "gwpTotal": gwp,
            "primaryEnergyNonRenewable": energy,
            "waterUse": water,
            "assessmentStandard": standard,
        }

    def set_circularity(self, recyclable_fraction: float, reusable: bool,
                        disassembly_instructions: str) -> None:
        self.circularity = {
            "recyclableMassFraction": recyclable_fraction,
            "designedForReuse": reusable,
            "disassemblyInstructions": disassembly_instructions,
        }

    def add_performance(self, property_name: str, value: str, unit: str,
                        standard: str = "", class_: str = "") -> None:
        self.performance[property_name] = {
            "value": value,
            "unit": unit,
            "standard": standard,
            "class": class_,
        }

    def add_attachment(self, doc_id: str, sha256: str) -> None:
        self.attachments[doc_id] = sha256

    def add_traceability_event(self, event: TraceabilityEvent) -> None:
        self.traceability.append(event)

    def recall(self) -> None:
        self.status = "recalled"

    # -- integrity ----------------------------------------------------------
    def document(self) -> Dict[str, Any]:
        return {
            "@context": DPP_CONTEXT,
            "@id": self.passport_id,
            "@type": "DigitalProductPassport",
            "materialPassportId": self.material_passport_id,
            "identification": {
                "name": self.name,
                "gtin": self.gtin,
                "productGroup": self.product_group,
                "serial": self.serial,
                "manufactureDate": self.manufacture_date,
                "productionSite": self.production_site,
                "manufacturer": self.manufacturer_did,
            },
            "status": self.status,
            "composition": list(self.composition),
            "sustainability": dict(self.sustainability),
            "circularity": dict(self.circularity),
            "performance": dict(self.performance),
            "maintenance": dict(self.maintenance),
            "traceability": [e.as_dict() for e in self.traceability],
            "attachments": dict(self.attachments),
        }

    def fingerprint(self) -> str:
        return crypto.content_hash(crypto.canonical_json(self.document()).encode())

    def signed_copy(self) -> Dict[str, Any]:
        return crypto.sign_document(self.manufacturer_did, self.document())


def verify_passport_document(manufacturer_did: str, doc: Dict[str, Any]) -> bool:
    return crypto.verify_document(manufacturer_did, doc)


def build_demo_passport(
    passport_id: str,
    manufacturer_did: str,
    *,
    name: str = "Precast concrete element",
    gwp: float = 210.0,
    with_recall: bool = False,
) -> DigitalProductPassport:
    """Factory producing a realistic building-component passport."""
    passport = DigitalProductPassport(
        passport_id=passport_id,
        name=name,
        gtin=f"426{abs(hash(passport_id)) % 10**10:010d}",
        product_group="concrete",
        manufacturer_did=manufacturer_did,
        production_site="Plant Nordrhein, DE",
        manufacture_date="2024-06-15",
        serial=f"SN-{passport_id[-6:]}",
    )
    passport.add_substance("Portland cement CEM II/A-LL", 0.28, recycled=False)
    passport.add_substance("Aggregates (gravel/sand)", 0.45)
    passport.add_substance("Recycled concrete aggregate", 0.12, recycled=True)
    passport.add_substance("Reinforcing steel B500B", 0.11, recycled=True)
    passport.add_substance("Water", 0.04)
    passport.set_sustainability(gwp=gwp, energy=1850.0, water=1200.0)
    passport.set_circularity(0.82, True, "bolted connections, separable layers")
    passport.add_performance("compressiveStrength", "45", "N/mm2", "EN 206", "C35/45")
    passport.add_performance("fireResistance", "REI", "min", "EN 13501-2", "REI90")
    passport.add_performance("thermalConductivity", "0.09", "W/mK", "EN 12667")
    passport.add_attachment("dop-2024-0042", "b7e4" + "c0" * 30)
    passport.add_attachment("epd-2024-0042", "aa1f" + "be" * 30)
    passport.add_traceability_event(
        TraceabilityEvent(
            timestamp=crypto.now_epoch() - 86400 * 12,
            actor_did=manufacturer_did,
            event_type="manufactured",
            location="Plant Nordrhein, DE",
            details={"line": "PC-07"},
        )
    )
    if with_recall:
        passport.recall()
    return passport
