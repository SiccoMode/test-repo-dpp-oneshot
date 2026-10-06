"""Tests for identity, credentials, policy evaluation and the ledger."""

import unittest

from dpp_dataspace.identity import Participant, ParticipantDirectory
from dpp_dataspace.ledger import EventLedger
from dpp_dataspace.policy import membership_only_policy, role_policy, Constraint


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.directory = ParticipantDirectory()

    def test_membership_credential_verifies(self):
        p = Participant(
            did="did:web:precast.example",
            display_name="Nordrhein Precast GmbH",
            roles=["provider"],
        )
        self.directory.register(p)
        self.assertTrue(self.directory.has_valid_membership(p.did))

    def test_unknown_participant_has_no_membership(self):
        self.assertFalse(self.directory.has_valid_membership("did:web:ghost.example"))

    def test_tampered_credential_detected(self):
        p = Participant(did="did:web:x.example", display_name="X", roles=["consumer"])
        self.directory.register(p)
        p.membership_credential["credentialSubject"]["roles"] = ["provider"]
        self.assertFalse(self.directory.has_valid_membership(p.did))

    def test_duplicate_registration_rejected(self):
        self.directory.register(Participant(did="did:web:a.example", display_name="A"))
        with self.assertRaises(ValueError):
            self.directory.register(Participant(did="did:web:a.example", display_name="A2"))


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.directory = ParticipantDirectory()

    def _consumer(self, **attributes):
        roles = attributes.pop("roles", ["consumer"])
        p = Participant(did="did:web:c.example", display_name="C", roles=roles,
                        attributes=attributes)
        self.directory.register(p)
        return p

    def test_membership_only_allows_any_member(self):
        consumer = self._consumer()
        result = membership_only_policy().evaluate(consumer)
        self.assertTrue(result["allowed"])

    def test_role_policy_denies_wrong_role(self):
        consumer = self._consumer(roles=["consumer"])
        result = role_policy(["recycler"]).evaluate(consumer)
        self.assertFalse(result["allowed"])
        self.assertIn("permission not satisfied", result["reason"])

    def test_role_policy_allows_matching_role(self):
        consumer = self._consumer(roles=["consumer", "recycler"])
        self.assertTrue(role_policy(["recycler"]).evaluate(consumer)["allowed"])

    def test_constraint_operators(self):
        c = Constraint("jurisdiction", "isAnyOf", ["DE", "FR"])
        self.assertTrue(c.evaluate({"jurisdiction": "DE"}))
        self.assertFalse(c.evaluate({"jurisdiction": "US"}))
        c2 = Constraint("jurisdiction", "isNoneOf", ["US"])
        self.assertTrue(c2.evaluate({"jurisdiction": "DE"}))
        self.assertFalse(c2.evaluate({"jurisdiction": "US"}))
        c3 = Constraint("roles", "isAllOf", ["a", "b"])
        self.assertTrue(c3.evaluate({"roles": ["a", "b", "c"]}))
        self.assertFalse(c3.evaluate({"roles": ["a"]}))


class TestLedger(unittest.TestCase):
    def test_chain_valid_and_tamper_evident(self):
        ledger = EventLedger()
        ledger.append("participant.joined", "did:web:a.example", {"name": "A"})
        ledger.append("agreement.created", "did:web:a.example", {"id": "agr:1"})
        self.assertTrue(ledger.verify_chain())
        ledger.entries()[1].payload["id"] = "agr:hacked"
        self.assertFalse(ledger.verify_chain())

    def test_append_ordering_and_lookup(self):
        ledger = EventLedger()
        a = ledger.append("e1", "did:web:a.example", {"n": 1})
        b = ledger.append("e2", "did:web:b.example", {"n": 2})
        self.assertEqual(b.seq, a.seq + 1)
        self.assertEqual(b.prev_hash, a.entry_hash)
        self.assertEqual(ledger.by_type("e1")[0].actor, "did:web:a.example")
        self.assertEqual(ledger.find(a.seq).entry_hash, a.entry_hash)


if __name__ == "__main__":
    unittest.main()
