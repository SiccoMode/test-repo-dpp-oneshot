"""Hash-chained event ledger for auditability of all dataspace interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import crypto


@dataclass
class LedgerEntry:
    seq: int
    timestamp: int
    event_type: str
    actor: str
    payload: Dict[str, Any]
    payload_hash: str
    prev_hash: str
    entry_hash: str


class EventLedger:
    """An append-only, hash-chained ledger. Tamper-evident, not tamper-proof."""

    def __init__(self) -> None:
        self._entries: List[LedgerEntry] = []

    def append(self, event_type: str, actor: str, payload: Dict[str, Any]) -> LedgerEntry:
        prev_hash = self._entries[-1].entry_hash if self._entries else "0" * 64
        payload_hash = crypto.content_hash(crypto.canonical_json(payload).encode())
        head = {
            "seq": len(self._entries),
            "event_type": event_type,
            "actor": actor,
            "payload_hash": payload_hash,
            "prev_hash": prev_hash,
        }
        entry_hash = crypto.content_hash(crypto.canonical_json(head).encode())
        entry = LedgerEntry(
            seq=len(self._entries),
            timestamp=crypto.now_epoch(),
            event_type=event_type,
            actor=actor,
            payload=dict(payload),
            payload_hash=payload_hash,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> List[LedgerEntry]:
        return list(self._entries)

    def by_type(self, event_type: str) -> List[LedgerEntry]:
        return [e for e in self._entries if e.event_type == event_type]

    def find(self, seq: int) -> Optional[LedgerEntry]:
        for entry in self._entries:
            if entry.seq == seq:
                return entry
        return None

    def verify_chain(self) -> bool:
        prev_hash = "0" * 64
        for index, entry in enumerate(self._entries):
            if entry.seq != index or entry.prev_hash != prev_hash:
                return False
            recomputed_payload = crypto.content_hash(
                crypto.canonical_json(entry.payload).encode()
            )
            recomputed_head = crypto.content_hash(
                crypto.canonical_json(
                    {
                        "seq": entry.seq,
                        "event_type": entry.event_type,
                        "actor": entry.actor,
                        "payload_hash": recomputed_payload,
                        "prev_hash": entry.prev_hash,
                    }
                ).encode()
            )
            if recomputed_head != entry.entry_hash:
                return False
            prev_hash = entry.entry_hash
        return True

    def latest_hash(self) -> str:
        return self._entries[-1].entry_hash if self._entries else "0" * 64
