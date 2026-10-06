"""Tiny in-process crypto primitives.

The testbed must run anywhere without wheels, so we model the security layer
with stdlib primitives: HMAC signatures and verifiable credential style JSON
documents. Clearly not production crypto - the goal is to exercise the
*protocol semantics* (who signed what, which credential applies to which
offer) rather than cryptographic strength.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Dict

# Deterministic, participant-scoped "key material" (not a real secret store).
KEYRING: Dict[str, bytes] = {}


def issue_key(participant_id: str) -> bytes:
    if participant_id not in KEYRING:
        KEYRING[participant_id] = hashlib.sha256(
            f"key::{participant_id}::{uuid.uuid4()}".encode()
        ).digest()
    return KEYRING[participant_id]


def canonical_json(doc: Any) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(participant_id: str, payload: bytes) -> str:
    key = issue_key(participant_id)
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify(participant_id: str, payload: bytes, signature: str) -> bool:
    key = issue_key(participant_id)
    return hmac.compare_digest(
        hmac.new(key, payload, hashlib.sha256).hexdigest(), signature
    )


def now_epoch() -> int:
    return int(time.time())


def sign_document(participant_id: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return {**body, "signature": sign(participant_id, canonical_json(body).encode())}


def verify_document(participant_id: str, doc: Dict[str, Any]) -> bool:
    body = {k: v for k, v in doc.items() if k != "signature"}
    signature = doc.get("signature")
    if not signature:
        return False
    return verify(participant_id, canonical_json(body).encode(), signature)


def content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
