# Paged Fleet inventories

Clients advertise `paged-inventory-v1` and request that transport on heartbeat.
The server transfers the complete signed desired state in 96 KiB byte pages.
Every page is bound to one revision, SHA-256 digest and length. A changed
revision invalidates the transfer. No partial inventory is applied.

The client checks continuity, the complete digest, the original Ed25519
signature, and its agent identity before reconciliation. Large manifests spill
to a temporary file while downloading. A transfer failure retains the previous
installed inventory.

There is no total package-count ceiling for negotiated paged inventories.
The frozen inline v1 contract retains its 256-item bound for legacy clients;
larger signed documents require the `paged-inventory-v1` extension. Legacy
clients retain their previous inventory until upgraded. HTTP response-size,
individual archive and authorization checks remain in force.
