#!/usr/bin/env python3
"""End-to-end demo of DPP data exchange in the building-materials dataspace.

Runs a full round trip: catalog discovery -> contract negotiation -> signed
agreement -> loopback HTTP transfer -> DPP verification -> project index,
then prints an audit summary from the hash-chained event ledger.

Usage: python3 demo.py
"""

from __future__ import annotations

import json

from dpp_dataspace import crypto
from dpp_dataspace.federation import (
    BuildingMaterialsDataspace,
    create_testbed,
    run_demo_scenario,
)
from dpp_dataspace.transfer import AccessDenied, LoopbackProviderServer
from dpp_dataspace.contract import PolicyDenied


def main() -> None:
    ds: BuildingMaterialsDataspace
    ds = create_testbed()
    print("=" * 70)
    print("DPP Testbed - building materials dataspace")
    print("=" * 70)
    print(f"Participants: {len(ds.directory.all_participants())}")
    for p in ds.directory.all_participants():
        cred_ok = ds.directory.has_valid_membership(p.did)
        print(f"  - {p.display_name:45s} {p.did}  membership={'OK' if cred_ok else 'MISSING'}")

    print("\n--- Catalog (precast provider) ---")
    for dataset in ds.catalog_of("did:web:precast.example").search()["datasets"]:
        print(f"  {dataset['offerId']}  {dataset['title']}")

    scenario = run_demo_scenario()
    index = scenario["index"]
    print("\n--- Project consumed passports ---")
    print(json.dumps(index.summary(), indent=2, sort_keys=True))

    print("\n--- Negative checks ---")
    resolver = ds.consumer_resolver("did:web:project.example")
    transfer = ds.transfer_service("did:web:precast.example")
    try:
        transfer.pull("did:web:project.example", "agr:unknown", "dpp:precast:PE-2024-0001")
        print("  unauthorized pull unexpectedly succeeded (!)")
    except AccessDenied as exc:
        print(f"  unauthorized pull denied: {exc.reason}")
    real_offer = ds.catalog_of("did:web:precast.example").search()["datasets"][0]["offerId"]
    try:
        ds.negotiate("did:web:precast.example", "did:web:unknown.example", real_offer)
    except Exception as exc:
        print(f"  non-member negotiation rejected: {type(exc).__name__}: {exc}")

    print("\n--- Ledger audit ---")
    for event_type, count in sorted(scenario["audit"].items()):
        print(f"  {event_type:35s} x{count}")
    print(f"\nLedger chain valid: {scenario['chainValid']}")
    print("Demo completed successfully.")


if __name__ == "__main__":
    main()
