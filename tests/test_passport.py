"""Unit tests for DPP document handling and integrity."""

import json
import unittest

from dpp_dataspace import crypto
from dpp_dataspace.passport import (
    DigitalProductPassport,
    build_demo_passport,
    verify_passport_document,
)


class TestPassport(unittest.TestCase):
    def test_document_shape(self):
        p = build_demo_passport("dpp:precast:PE-2024-0001", "did:web:precast.example")
        doc = p.document()
        self.assertEqual(doc["@type"], "DigitalProductPassport")
        self.assertEqual(doc["identification"]["manufacturer"], "did:web:precast.example")
        self.assertEqual(len(doc["composition"]), 5)
        self.assertEqual(doc["status"], "active")
        self.assertTrue(doc["sustainability"]["gwpTotal"] > 0)

    def test_fingerprint_stable_and_sensitive(self):
        p = build_demo_passport("dpp:precast:PE-2024-0001", "did:web:precast.example")
        f1 = p.fingerprint()
        f2 = p.fingerprint()
        self.assertEqual(f1, f2)
        p.recall()
        self.assertNotEqual(f1, p.fingerprint())

    def test_signed_copy_roundtrip(self):
        p = build_demo_passport("dpp:precast:PE-2024-0001", "did:web:precast.example")
        signed = p.signed_copy()
        self.assertTrue(
            verify_passport_document("did:web:precast.example", signed)
        )
        tampered = json.loads(json.dumps(signed))
        tampered["status"] = "forged"
        self.assertFalse(
            verify_passport_document("did:web:precast.example", tampered)
        )

    def test_wrong_issuer_fails(self):
        p = build_demo_passport("dpp:precast:PE-2024-0001", "did:web:precast.example")
        signed = p.signed_copy()
        self.assertFalse(
            verify_passport_document("did:web:attacker.example", signed)
        )

    def test_recall_flow(self):
        p = build_demo_passport(
            "dpp:precast:PE-2024-0009", "did:web:precast.example", with_recall=True
        )
        self.assertEqual(p.document()["status"], "recalled")


if __name__ == "__main__":
    unittest.main()
