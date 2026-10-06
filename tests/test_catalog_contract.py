"""Tests for catalog discovery and contract negotiation."""

import unittest

from dpp_dataspace.federation import create_testbed
from dpp_dataspace.contract import PolicyDenied, NegotiationError


class TestCatalogAndNegotiation(unittest.TestCase):
    def setUp(self):
        self.ds = create_testbed()

    def test_catalog_lists_offers_with_paging(self):
        page = self.ds.catalog_of("did:web:precast.example").search()
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["datasets"]), 2)
        page1 = self.ds.catalog_of("did:web:precast.example").search(page=1, page_size=1)
        self.assertEqual(len(page1["datasets"]), 1)
        page2 = self.ds.catalog_of("did:web:precast.example").search(page=2, page_size=1)
        self.assertEqual(len(page2["datasets"]), 1)
        self.assertNotEqual(page1["datasets"][0]["assetId"], page2["datasets"][0]["assetId"])

    def test_catalog_search_filters(self):
        hits = self.ds.catalog_of("did:web:precast.example").search("slab")
        self.assertEqual(hits["total"], 1)
        self.assertIn("slab", hits["datasets"][0]["title"].lower())

    def test_unknown_offer_rejected(self):
        with self.assertRaises(LookupError):
            self.ds.catalog_of("did:web:precast.example").require("offer:none")

    def test_negotiation_creates_agreement(self):
        offers = self.ds.catalog_of("did:web:precast.example").search()["datasets"]
        agreement = self.ds.negotiate(
            "did:web:precast.example", "did:web:project.example", offers[0]["offerId"]
        )
        self.assertEqual(agreement.consumer_did, "did:web:project.example")
        self.assertTrue(self.ds.providers["did:web:precast.example"]["negotiations"]
                        .verify_agreement(agreement.agreement_id))

    def test_non_member_cannot_negotiate(self):
        offers = self.ds.catalog_of("did:web:precast.example").search()["datasets"]
        with self.assertRaises(NegotiationError):
            self.ds.negotiate(
                "did:web:precast.example", "did:web:stranger.example", offers[0]["offerId"]
            )

    def test_policy_denies_role_mismatch(self):
        # offer for asset 0001 requires consumer or recycler; steel provider is not
        offer = "dpp:precast:PE-2024-0001"
        catalog = self.ds.catalog_of("did:web:precast.example")
        with self.assertRaises(PolicyDenied):
            self.ds.negotiate(
                "did:web:precast.example", "did:web:steel.example",
                catalog.require_by_asset(offer),
            )

    def test_terminate_requires_party(self):
        offers = self.ds.catalog_of("did:web:precast.example").search()["datasets"]
        agreement = self.ds.negotiate(
            "did:web:precast.example", "did:web:project.example", offers[0]["offerId"]
        )
        negotiations = self.ds.providers["did:web:precast.example"]["negotiations"]
        with self.assertRaises(NegotiationError):
            negotiations.terminate(agreement.agreement_id, "did:web:stranger.example")
        negotiations.terminate(agreement.agreement_id, "did:web:project.example")
        self.assertFalse(negotiations.verify_agreement(agreement.agreement_id))


if __name__ == "__main__":
    unittest.main()
