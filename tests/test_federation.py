"""Tests for the federation-level scenario wiring."""

import unittest

from dpp_dataspace import crypto
from dpp_dataspace.federation import create_testbed, run_demo_scenario


class TestFederationScenario(unittest.TestCase):
    def test_demo_scenario_end_to_end(self):
        scenario = run_demo_scenario()
        self.assertEqual(len(scenario["resolved"]), 2)
        self.assertTrue(all(r.verified for r in scenario["resolved"]))
        self.assertTrue(scenario["chainValid"])
        audit = scenario["audit"]
        self.assertEqual(audit["agreement.created"], 2)
        self.assertEqual(audit["transfer.completed"], 2)

    def test_testbed_membership(self):
        ds = create_testbed()
        for participant in ds.directory.all_participants():
            self.assertTrue(ds.directory.has_valid_membership(participant.did),
                            participant.did)

    def test_offers_published_for_all_providers(self):
        ds = create_testbed()
        self.assertEqual(ds.catalog_of("did:web:precast.example").stats()["offers"], 2)
        self.assertEqual(ds.catalog_of("did:web:steel.example").stats()["offers"], 1)

    def test_agreement_signature_verifies(self):
        ds = create_testbed()
        offer_id = ds.catalog_of("did:web:steel.example").require_by_asset(
            "dpp:steel:SB-2024-0007"
        )
        agreement = ds.negotiate("did:web:steel.example", "did:web:project.example", offer_id)
        payload = (
            f"{agreement.agreement_id}|{agreement.asset_id}|{agreement.consumer_did}"
        ).encode()
        self.assertTrue(crypto.verify(agreement.provider_did, payload, agreement.signature))


if __name__ == "__main__":
    unittest.main()
