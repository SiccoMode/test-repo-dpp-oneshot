#!/usr/bin/env python3
"""Locally hosted development server for the DPP testbed.

Runs a loopback-only HTTP server (default http://127.0.0.1:8080) that serves:

- ``/``            a small HTML dashboard showing participants, catalog offers,
                   consumed passports and the ledger audit trail
- ``/api/state``   full testbed state as JSON (participants, catalogs, ledger)
- ``/api/catalog`` per-provider catalog search
- ``/api/negotiate`` run one contract negotiation (consumer, offer) as a POST
- ``/api/ledger``  hash-chained ledger entries
- ``/api/audit``   event-type counts + chain validity

The server binds to 127.0.0.1 only; this is a local development tool, not a
public deployment. Run with: python3 dev_server.py [--port 8080]
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from dpp_dataspace.contract import NegotiationError, PolicyDenied
from dpp_dataspace.federation import BuildingMaterialsDataspace, create_testbed
from dpp_dataspace.resolver import ProjectDppIndex
from dpp_dataspace.transfer import LoopbackProviderServer

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DPP Testbed - Building Materials Dataspace</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; background: #f6f7f9; color: #1c2430; }
  h1 { margin-bottom: .25rem; } .sub { color: #5a6572; margin-bottom: 2rem; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  .card { background: #fff; border: 1px solid #e3e7ec; border-radius: 10px; padding: 1rem 1.25rem; }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; }
  th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #eef1f4; }
  th { color: #5a6572; font-weight: 600; }
  .ok { color: #127a3d; } .bad { color: #b3261e; }
  pre { background: #f0f2f5; padding: .75rem; border-radius: 8px; font-size: .8rem; overflow-x: auto; }
  button { padding: .5rem 1rem; border: 0; border-radius: 8px; background: #1c4d8c; color: #fff; cursor: pointer; }
  #msg { margin-top: .5rem; font-size: .85rem; }
</style>
</head>
<body>
<h1>DPP Testbed &mdash; Building Materials Dataspace</h1>
<p class="sub">Local development server (loopback only). Participants, catalog,
contract negotiation, DPP transfer and audit ledger at a glance.</p>
<div class="grid">
  <div class="card"><h3>Participants</h3><table id="participants"></table></div>
  <div class="card"><h3>Catalog offers</h3><table id="offers"></table></div>
  <div class="card"><h3>Consumed passports (project BlueTower)</h3><table id="passports"></table></div>
  <div class="card"><h3>Run an exchange</h3>
    <p>Negotiate + pull one DPP as the project consumer:</p>
    <select id="offer"></select>
    <button onclick="runExchange()">Negotiate &amp; pull DPP</button>
    <p id="msg"></p>
  </div>
  <div class="card"><h3>Audit ledger (latest events)</h3><table id="ledger"></table></div>
  <div class="card"><h3>API</h3>
    <p><a href="/api/state">/api/state</a> &middot; <a href="/api/catalog">/api/catalog</a> &middot;
       <a href="/api/ledger">/api/ledger</a> &middot; <a href="/api/audit">/api/audit</a></p>
    <pre>curl http://127.0.0.1:PORT/api/state | jq .audit</pre>
  </div>
</div>
<script>
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function row(cells, tag) {
  const tr = document.createElement('tr');
  cells.forEach(c => { const el = document.createElement(tag); el.innerHTML = esc(c); tr.appendChild(el); });
  return tr;
}
function fill(id, headers, rows) {
  const t = document.getElementById(id); t.innerHTML = '';
  const thead = document.createElement('thead');
  thead.appendChild(row(headers, 'th')); t.appendChild(thead);
  const tbody = document.createElement('tbody');
  rows.forEach(r => tbody.appendChild(row(r, 'td'))); t.appendChild(tbody);
}
async function refresh() {
  const state = await (await fetch('/api/state')).json();
  fill('participants', ['DID', 'Name', 'Roles', 'Membership'],
    state.participants.map(p => [p.did, p.displayName, p.roles.join(', '),
      p.membershipValid ? 'OK' : 'INVALID']));
  fill('offers', ['Offer', 'Provider', 'Title', 'Asset'],
    state.offers.map(o => [o.offerId, o.provider, o.title, o.assetId]));
  fill('passports', ['Asset', 'Material', 'GWP', 'Signature'],
    state.project.passports.map(p => [p.assetId, p.name, p.gwp, p.verified ? 'verified' : 'UNVERIFIED']));
  const latest = state.ledger.slice(-12).reverse();
  fill('ledger', ['#', 'Event', 'Actor', 'Payload hash'],
    latest.map(e => [e.seq, e.eventType, e.actor, e.payloadHash.slice(0, 12) + '...']));
  const sel = document.getElementById('offer'); sel.innerHTML = '';
  state.offers.forEach(o => {
    const opt = document.createElement('option');
    opt.value = o.offerId + '|' + o.provider + '|' + o.assetId;
    opt.textContent = o.title;
    sel.appendChild(opt);
  });
}
async function runExchange() {
  const [offerId, provider, assetId] = document.getElementById('offer').value.split('|');
  const msg = document.getElementById('msg');
  msg.textContent = 'negotiating...';
  const res = await fetch('/api/negotiate', { method: 'POST', body: JSON.stringify({ offerId, provider, assetId }) });
  const body = await res.json();
  msg.textContent = res.ok ? 'Pulled ' + assetId + ' (verified: ' + body.verified + ')'
                          : 'Failed: ' + body.error + ' / ' + (body.reason || '');
  refresh();
}
refresh(); setInterval(refresh, 5000);
</script>
</body>
</html>
"""


class DevServer:
    """Loopback-only dev server wrapping a live testbed instance."""

    def __init__(self, port: int = 8080) -> None:
        self.dataspace: BuildingMaterialsDataspace = create_testbed()
        self.project_index = ProjectDppIndex(project_id="BlueTower")
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- state assembly ------------------------------------------------------
    def state(self) -> Dict[str, Any]:
        ds = self.dataspace
        participants = []
        for p in ds.directory.all_participants():
            participants.append(
                {
                    "did": p.did,
                    "displayName": p.display_name,
                    "roles": p.roles,
                    "membershipValid": ds.directory.has_valid_membership(p.did),
                }
            )
        offers = []
        for provider_did, entry in ds.providers.items():
            catalog = entry["catalog"]
            for dataset in catalog.search(page_size=100)["datasets"]:
                offers.append(
                    {
                        "offerId": dataset["offerId"],
                        "provider": provider_did,
                        "title": dataset["title"],
                        "assetId": dataset["assetId"],
                        "policy": dataset["policy"],
                    }
                )
        passports = []
        for resolved in self.project_index.entries:
            identification = resolved.document.get("identification", {})
            passports.append(
                {
                    "assetId": resolved.asset_id,
                    "name": identification.get("name", ""),
                    "gwp": resolved.document.get("sustainability", {}).get("gwpTotal"),
                    "verified": resolved.verified,
                    "fingerprint": resolved.fingerprint,
                }
            )
        return {
            "participants": participants,
            "offers": offers,
            "project": {
                "projectId": self.project_index.project_id,
                "summary": self.project_index.summary(),
                "passports": passports,
            },
            "ledger": [
                {
                    "seq": e.seq,
                    "eventType": e.event_type,
                    "actor": e.actor,
                    "payloadHash": e.payload_hash,
                    "entryHash": e.entry_hash,
                    "payload": e.payload,
                }
                for e in self.dataspace.ledger.entries()
            ],
        }

    # -- exchange actions ------------------------------------------------------
    def negotiate_and_pull(self, provider_did: str, consumer_did: str,
                           offer_id: str) -> Dict[str, Any]:
        ds = self.dataspace
        with self._lock:
            entry = ds.providers.get(provider_did)
            if entry is None:
                raise LookupError(f"unknown provider: {provider_did}")
            catalog = entry["catalog"]
            offer = catalog.require(offer_id)
            negotiation = entry["negotiations"]
            result = negotiation.initiate(consumer_did, offer_id)
            agreement = negotiation.agree(result["negotiationId"])
            resolver = ds.consumer_resolver(consumer_did)
            with LoopbackProviderServer(entry["transfer"]) as server:
                resolved = resolver.resolve(server.endpoint, agreement, offer.asset_id)
            self.project_index.add(resolved)
            return {
                "agreementId": agreement.agreement_id,
                "assetId": offer.asset_id,
                "fingerprint": resolved.fingerprint,
                "verified": resolved.verified,
            }

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> str:
        if self._server is not None:
            raise RuntimeError("dev server already running")
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None

    def __enter__(self) -> "DevServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def _make_handler(dev: DevServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DPPDevServer/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", DASHBOARD_HTML.encode())
            elif parsed.path == "/api/state":
                self._json(200, dev.state())
            elif parsed.path == "/api/catalog":
                provider = parse_qs(parsed.query).get("provider")
                provider_did = (provider or ["did:web:precast.example"])[0]
                try:
                    catalog = dev.dataspace.catalog_of(provider_did)
                except KeyError:
                    self._json(404, {"error": "unknown provider"})
                    return
                self._json(200, catalog.search(page_size=100))
            elif parsed.path == "/api/ledger":
                self._json(200, {"entries": dev.state()["ledger"]})
            elif parsed.path == "/api/audit":
                state = dev.state()
                counts: Dict[str, int] = {}
                for e in state["ledger"]:
                    counts[e["eventType"]] = counts.get(e["eventType"], 0) + 1
                self._json(200, {"counts": counts, "chainValid": dev.dataspace.ledger.verify_chain()})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON body"})
                return
            if parsed.path != "/api/negotiate":
                self._json(404, {"error": "not found"})
                return
            offer_id = body.get("offerId", "")
            provider = body.get("provider", "")
            consumer = body.get("consumer", "did:web:project.example")
            try:
                result = dev.negotiate_and_pull(provider, consumer, offer_id)
            except PolicyDenied as exc:
                self._json(403, {"error": "policy denied", "reason": exc.reason})
            except (LookupError, NegotiationError) as exc:
                self._json(400, {"error": "negotiation failed", "reason": str(exc)})
            else:
                self._json(200, result)

        def _json(self, status: int, body: Dict[str, Any]) -> None:
            self._send(status, "application/json", json.dumps(body, sort_keys=True).encode())

        def _send(self, status: int, ctype: str, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="DPP testbed dev server (loopback only)")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = DevServer(port=args.port)
    url = server.start()
    print(f"DPP testbed dev server running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        import signal

        signal.signal(signal.SIGINT, signal.default_int_handler)
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("dev server stopped")


if __name__ == "__main__":
    main()
