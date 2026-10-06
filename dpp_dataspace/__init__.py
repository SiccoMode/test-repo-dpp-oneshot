"""In-process testbed for Digital Product Passport (DPP) data exchange.

Models the core moving parts of a dataspace (inspired by the Eclipse Dataspace
Components and the Dataspace Protocol) specialised for building materials and
components:

- DID-based participant identity and signed membership credentials
- A DCP-style catalog publishing DPP-bearing offers per material asset
- An EDC-style contract negotiation state machine with policy evaluation
- Loopback HTTP artifact pull transfers authorized by contract agreements
- A hash-chained event ledger for auditability

Everything runs in-process on loopback interfaces only; no external services.
"""

__version__ = "0.1.0"
