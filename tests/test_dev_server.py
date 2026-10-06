"""Tests for the loopback dev server (dashboard + JSON API)."""

import json
import unittest
import urllib.request

from dev_server import DevServer


class TestDevServer(unittest.TestCase):
    def setUp(self):
        self.server = DevServer(port=0)
        self.url = self.server.start()
        self.addCleanup(self.server.stop)

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.url + path, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def _post(self, path, body):
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_dashboard_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Building Materials Dataspace", body)

    def test_state_endpoint(self):
        status, body = self._get("/api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual(len(state["participants"]), 4)
        self.assertEqual(len(state["offers"]), 3)
        self.assertTrue(all(p["membershipValid"] for p in state["participants"]))
        self.assertEqual(state["project"]["summary"]["passports"], 0)

    def test_catalog_endpoint(self):
        status, body = self._get("/api/catalog?provider=did:web:steel.example")
        self.assertEqual(status, 200)
        page = json.loads(body)
        self.assertEqual(page["total"], 1)
        self.assertIn("Steel beam DPP", page["datasets"][0]["title"])

    def test_negotiate_endpoint_full_exchange(self):
        status, body = self._get("/api/state")
        offers = json.loads(body)["offers"]
        target = next(o for o in offers if o["title"] == "Steel beam DPP")
        status, result = self._post("/api/negotiate", {
            "offerId": target["offerId"],
            "provider": target["provider"],
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["verified"])
        self.assertTrue(result["agreementId"].startswith("agr:"))
        state = json.loads(self._get("/api/state")[1])
        self.assertEqual(state["project"]["summary"]["passports"], 1)

    def test_negotiate_unknown_offer_400(self):
        status, body = self._post("/api/negotiate", {
            "offerId": "offer:none", "provider": "did:web:precast.example",
        })
        self.assertEqual(status, 400)
        self.assertIn("reason", body)

    def test_negotiate_non_member_400(self):
        status, body = self._get("/api/state")
        offers = json.loads(body)["offers"]
        status, body = self._post("/api/negotiate", {
            "offerId": offers[0]["offerId"],
            "provider": offers[0]["provider"],
            "consumer": "did:web:stranger.example",
        })
        self.assertEqual(status, 400)
        self.assertIn("membership", body["reason"])

    def test_ledger_and_audit(self):
        status, body = self._get("/api/ledger")
        entries = json.loads(body)["entries"]
        self.assertGreater(len(entries), 0)
        self.assertEqual(entries[0]["eventType"], "participant.joined")
        status, body = self._get("/api/audit")
        audit = json.loads(body)
        self.assertTrue(audit["chainValid"])
        self.assertGreaterEqual(audit["counts"]["catalog.offer.published"], 3)

    def test_unknown_path_404(self):
        status, body = self._get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
