"""End-to-end tests: negotiation -> HTTP transfer -> verification -> index."""

import json
import unittest

from dpp_dataspace.federation import create_testbed
from dpp_dataspace.transfer import (
    AccessDenied,
    LoopbackProviderServer,
    http_pull,
)


class TestTransferPipeline(unittest.TestCase):
    def setUp(self):
        self.ds = create_testbed()
        self.resolver = self.ds.consumer_resolver("did:web:project.example")

    def _first_agreement(self, provider="did:web:precast.example", query="Precast"):
        offers = self.ds.catalog_of(provider).search(query)["datasets"]
        self.assertTrue(offers)
        return self.ds.negotiate(provider, "did:web:project.example", offers[0]["offerId"])

    def test_full_pull_over_loopback_http(self):
        agreement = self._first_agreement()
        asset_id = agreement.asset_id
        expected_hash = None
        with LoopbackProviderServer(self.ds.transfer_service("did:web:precast.example")) as server:
            status, body = http_pull(
                server.endpoint, "did:web:project.example", agreement.agreement_id, asset_id
            )
        self.assertEqual(status, 200)
        document = json.loads(body)
        self.assertEqual(document["@id"], asset_id)
        self.assertTrue(document["signature"])

    def test_resolver_verifies_signature_and_hash(self):
        agreement = self._first_agreement()
        with LoopbackProviderServer(self.ds.transfer_service("did:web:precast.example")) as server:
            resolved = self.resolver.resolve(server.endpoint, agreement, agreement.asset_id)
        self.assertTrue(resolved.verified)
        self.assertEqual(resolved.fingerprint, resolved.fingerprint)
        catalog = self.ds.catalog_of("did:web:precast.example")
        offer = catalog.require_by_asset(agreement.asset_id)
        dataset = [d for d in catalog.search()["datasets"] if d["assetId"] == agreement.asset_id][0]
        self.assertEqual(resolved.fingerprint, dataset["dppHash"])

    def test_tampered_artifact_hash_mismatch(self):
        agreement = self._first_agreement()
        tampered = b'{"@id": "dpp:precast:PE-2024-0001", "hacked": true}'
        with self.assertRaises(RuntimeError):
            self.resolver.verify(agreement.asset_id, tampered, agreement.agreement_id,
                                 expected_hash="deadbeef" * 8)

    def test_denied_without_agreement(self):
        with LoopbackProviderServer(self.ds.transfer_service("did:web:precast.example")) as server:
            status, body = http_pull(
                server.endpoint, "did:web:project.example", "agr:none",
                "dpp:precast:PE-2024-0001"
            )
        self.assertEqual(status, 403)
        self.assertIn(b"access denied", body)
        denied = self.ds.ledger.by_type("transfer.denied")
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0].payload["reason"], "unknown agreement")

    def test_denied_for_wrong_consumer(self):
        agreement = self._first_agreement()
        transfer = self.ds.transfer_service("did:web:precast.example")
        with self.assertRaises(AccessDenied):
            transfer.pull(
                "did:web:recycler.example", agreement.agreement_id, agreement.asset_id
            )

    def test_denied_after_termination(self):
        agreement = self._first_agreement()
        transfer = self.ds.transfer_service("did:web:precast.example")
        transfer.pull("did:web:project.example", agreement.agreement_id, agreement.asset_id)
        self.ds.providers["did:web:precast.example"]["negotiations"].terminate(
            agreement.agreement_id, "did:web:project.example"
        )
        with self.assertRaises(AccessDenied):
            transfer.pull("did:web:project.example", agreement.agreement_id, agreement.asset_id)

    def test_denied_when_asset_not_covered(self):
        agreement = self._first_agreement()
        transfer = self.ds.transfer_service("did:web:precast.example")
        with self.assertRaises(AccessDenied):
            transfer.pull(
                "did:web:project.example", agreement.agreement_id, "dpp:steel:SB-2024-0007"
            )

    def test_missing_artifact_404(self):
        agreement = self._first_agreement()
        store = self.ds.providers["did:web:precast.example"]["store"]
        store._artifacts.pop(agreement.asset_id)
        store._hashes.pop(agreement.asset_id)
        with LoopbackProviderServer(self.ds.transfer_service("did:web:precast.example")) as server:
            status, body = http_pull(
                server.endpoint, "did:web:project.example",
                agreement.agreement_id, agreement.asset_id
            )
        self.assertEqual(status, 404)
        self.assertIn(b"unknown asset", body)

    def test_non_loopback_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            http_pull("http://192.0.2.1:9/api/v1/dpp", "x", "y", "z")

    def test_project_index_summary(self):
        from dpp_dataspace.resolver import ProjectDppIndex

        index = ProjectDppIndex(project_id="BlueTower")
        with LoopbackProviderServer(self.ds.transfer_service("did:web:precast.example")) as server:
            for dataset in self.ds.catalog_of("did:web:precast.example").search()["datasets"]:
                agreement = self.ds.negotiate(
                    "did:web:precast.example", "did:web:project.example", dataset["offerId"]
                )
                index.add(self.resolver.resolve(server.endpoint, agreement, dataset["assetId"]))
        summary = index.summary()
        self.assertEqual(summary["passports"], 2)
        self.assertEqual(summary["unverifiedCount"], 0)
        self.assertEqual(summary["recalledCount"], 0)
        self.assertGreater(summary["totalGwp"], 0)
        self.assertTrue(all(r.verified for r in index.entries))

    def test_ledger_records_full_chain_of_custody(self):
        agreement = self._first_agreement()
        with LoopbackProviderServer(self.ds.transfer_service("did:web:precast.example")) as server:
            self.resolver.resolve(server.endpoint, agreement, agreement.asset_id)
        events = [e.event_type for e in self.ds.ledger.entries()]
        self.assertIn("participant.joined", events)
        self.assertIn("catalog.offer.published", events)
        self.assertIn("negotiation.requested", events)
        self.assertIn("agreement.created", events)
        self.assertIn("transfer.completed", events)
        self.assertTrue(self.ds.ledger.verify_chain())


if __name__ == "__main__":
    unittest.main()
