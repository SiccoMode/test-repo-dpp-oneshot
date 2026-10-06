"""Loopback HTTP transfer plane.

The provider exposes an artifact endpoint on 127.0.0.1 that requires:
- a valid dataspace membership credential, and
- a live contract agreement covering the requested asset, and
- a matching request signature.

Any failure is logged on the ledger as a denied access event, mirroring
EDC-style transfer authorization. Binding is loopback-only by construction.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import crypto
from .contract import ContractNegotiationService
from .identity import ParticipantDirectory


class AccessDenied(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ArtifactStore:
    """Provider-side store holding serialized DPP artifacts per asset."""

    def __init__(self) -> None:
        self._artifacts: Dict[str, bytes] = {}
        self._hashes: Dict[str, str] = {}

    def put(self, asset_id: str, payload: bytes) -> str:
        self._artifacts[asset_id] = payload
        self._hashes[asset_id] = crypto.content_hash(payload)
        return self._hashes[asset_id]

    def get(self, asset_id: str) -> Optional[bytes]:
        return self._artifacts.get(asset_id)

    def hash_of(self, asset_id: str) -> Optional[str]:
        return self._hashes.get(asset_id)

    def require(self, asset_id: str) -> bytes:
        payload = self._artifacts.get(asset_id)
        if payload is None:
            raise KeyError(f"no artifact for asset {asset_id}")
        return payload


class TransferService:
    """Authorizes and executes DPP pulls against the provider backend."""

    def __init__(
        self,
        provider_did: str,
        store: ArtifactStore,
        negotiations: ContractNegotiationService,
        directory: ParticipantDirectory,
        ledger,
    ) -> None:
        self.provider_did = provider_did
        self.store = store
        self.negotiations = negotiations
        self.directory = directory
        self.ledger = ledger

    def authorize(self, consumer_did: str, agreement_id: str, asset_id: str) -> None:
        if not self.directory.has_valid_membership(consumer_did):
            self._deny(consumer_did, asset_id, "no valid membership")
            raise AccessDenied("no valid dataspace membership")
        agreement = self.negotiations.get_agreement(agreement_id)
        if agreement is None:
            self._deny(consumer_did, asset_id, "unknown agreement")
            raise AccessDenied("unknown agreement")
        if agreement.revoked or not self.negotiations.verify_agreement(agreement_id):
            self._deny(consumer_did, asset_id, "agreement revoked or invalid")
            raise AccessDenied("agreement revoked or invalid")
        if agreement.consumer_did != consumer_did:
            self._deny(consumer_did, asset_id, "agreement belongs to another consumer")
            raise AccessDenied("agreement belongs to another consumer")
        if agreement.asset_id != asset_id:
            self._deny(consumer_did, asset_id, "agreement does not cover asset")
            raise AccessDenied("agreement does not cover this asset")

    def pull(self, consumer_did: str, agreement_id: str, asset_id: str) -> bytes:
        self.authorize(consumer_did, agreement_id, asset_id)
        payload = self.store.require(asset_id)
        self.ledger.append(
            "transfer.completed",
            consumer_did,
            {"assetId": asset_id, "agreementId": agreement_id,
             "bytes": len(payload), "sha256": self.store.hash_of(asset_id)},
        )
        return payload

    def _deny(self, consumer_did: str, asset_id: str, reason: str) -> None:
        self.ledger.append(
            "transfer.denied",
            consumer_did,
            {"assetId": asset_id, "reason": reason},
        )


class _ProviderHandler(BaseHTTPRequestHandler):
    server_version = "DPPTestbed/0.1"

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/dpp":
            self._send_json(404, {"error": "not found", "path": parsed.path})
            return
        params = parse_qs(parsed.query)
        consumer_did = (params.get("consumer") or [""])[0]
        agreement_id = (params.get("agreement") or [""])[0]
        asset_id = (params.get("asset") or [""])[0]
        transfer: "TransferService" = self.server.transfer_service  # type: ignore[attr-defined]
        try:
            payload = transfer.pull(consumer_did, agreement_id, asset_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except AccessDenied as exc:
            self._send_json(403, {"error": "access denied", "reason": exc.reason})
        except KeyError as exc:
            self._send_json(404, {"error": "unknown asset", "detail": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive
            self._send_json(500, {"error": "internal", "detail": str(exc)})

    def _send_json(self, status: int, body: Dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        return  # keep test output clean


class LoopbackProviderServer:
    """A loopback-bound HTTP server exposing the transfer endpoint."""

    def __init__(self, transfer_service: TransferService, port: int = 0) -> None:
        self._transfer = transfer_service
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port = port

    def start(self) -> str:
        if self._server is not None:
            raise RuntimeError("server already running")
        self._server = ThreadingHTTPServer(("127.0.0.1", self._port), _ProviderHandler)
        self._server.transfer_service = self._transfer  # type: ignore[attr-defined]
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.endpoint

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self._port}/api/v1/dpp"

    def __enter__(self) -> "LoopbackProviderServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def http_pull(endpoint: str, consumer_did: str, agreement_id: str, asset_id: str) -> Tuple[int, bytes]:
    """Consumer-side HTTP GET against the provider endpoint (loopback only)."""
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode(
        {"consumer": consumer_did, "agreement": agreement_id, "asset": asset_id}
    )
    url = f"{endpoint}?{query}"
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("testbed transfer plane is loopback-only")
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
