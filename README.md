# DPP Testbed — Building Materials Dataspace

A self-contained, in-process testbed for **Digital Product Passport (DPP) data
exchange** in a **dataspace for building materials and components**, modelled on
the Dataspace Protocol / Eclipse Dataspace Components (EDC) and the emerging
CEN/CLC JTC 24 (EN 17665-style) construction DPP.

## What it simulates

| Dataspace concept | Testbed module |
|---|---|
| DID identity + signed membership credentials | `identity.py`, `crypto.py` |
| ODRL-style policy / constraint evaluation | `policy.py` |
| DCP-style catalog with dataset offers, search & paging | `catalog.py` |
| EDC-style contract negotiation + signed agreements | `contract.py` |
| Loopback HTTP transfer plane (EDR-style authorized pull) | `transfer.py` |
| Consumer-side DPP resolution & verification | `resolver.py` |
| Hash-chained event ledger (chain of custody, audit) | `ledger.py` |
| Federation wiring + demo scenario | `federation.py` |

The DPP documents (`passport.py`) follow a construction-product structure:
identification, composition (incl. recycled fractions), sustainability (GWP
per EN 15804+A2), circularity, performance (EN 206 / EN 13501-2), maintenance,
traceability events and attachment hashes (DoP, EPD).

## Scenario

`create_testbed()` wires up a building-materials dataspace:

- **Providers**: *Nordrhein Precast GmbH* (2 precast concrete DPPs) and
  *Ruhr Stahlwerke AG* (1 structural steel beam DPP), each running a catalog,
  negotiation service and loopback artifact endpoint.
- **Consumers**: *BauCycle Recycling eG* (recycler role) and *K&G
  Bauunternehmen* (construction project "BlueTower").
- **Policies**: one offer requires `consumer` or `recycler` roles, the others
  require only valid dataspace membership.

The demo round trip: catalog discovery → contract negotiation → signed
agreement → authorized HTTP pull (`127.0.0.1` only) → DPP signature
verification → project passport index (with GWP aggregation, recall and
unverified counts) → ledger audit with chain verification.

## Usage

```bash
# local dev server: dashboard + JSON API on http://127.0.0.1:8080 (loopback only)
python3 dev_server.py [--port 8080]

# end-to-end demo
python3 demo.py

# full test suite (stdlib unittest, no dependencies)
python3 -m unittest discover -s tests -v
```

### Dev server endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | HTML dashboard (participants, offers, passports, ledger) |
| `/api/state` | GET | Full testbed state as JSON |
| `/api/catalog?provider=<did>` | GET | Per-provider catalog search |
| `/api/negotiate` | POST | Run one negotiation + DPP pull (`{"offerId", "provider", "consumer"?}`) |
| `/api/ledger` | GET | Hash-chained ledger entries |
| `/api/audit` | GET | Event counts + chain validity |

The server binds to `127.0.0.1` only — it is a local development tool, not a
public deployment.

## Security model

- HMAC-signed membership credentials and DPP documents; tampering is detected.
- Agreement signatures authorize transfers; every pull is checked against
  membership, agreement validity, consumer identity and asset coverage.
- All denials are recorded on the ledger as `transfer.denied` events.
- The HTTP transfer plane is loopback-only (`127.0.0.1`) by construction and
  rejects non-loopback endpoints.

Note: the crypto layer intentionally uses stdlib HMAC to keep the testbed
dependency-free — it models protocol *semantics*, not production-grade
cryptography.

## Layout

```
dpp-testbed/
├── dev_server.py             # loopback dev server (dashboard + JSON API)
├── demo.py                    # runnable end-to-end scenario
├── dpp_dataspace/
│   ├── crypto.py              # signing / hashing primitives
│   ├── identity.py            # participants, directory, credentials
│   ├── policy.py              # ODRL-style constraint engine
│   ├── catalog.py             # DCP-style catalog service
│   ├── contract.py            # negotiation state machine + agreements
│   ├── transfer.py            # artifact store + loopback HTTP server
│   ├── resolver.py            # consumer verification + project index
│   ├── ledger.py              # hash-chained audit ledger
│   ├── passport.py            # DPP document model
│   └── federation.py          # dataspace wiring + scenario factory
└── tests/                     # 45 unittest cases across 6 modules
```
