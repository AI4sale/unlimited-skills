# Paged Fleet inventories

Clients advertise `paged-inventory-v1` and request that transport on heartbeat.
The server transfers the complete signed desired state in 96 KiB byte pages.
Every page is bound to one revision, SHA-256 digest and length. A changed
revision invalidates the transfer. An incomplete signed delivery plan is not
trusted. Once verified, its packages are processed independently.

The client checks continuity, the complete digest, the original Ed25519
signature, and its agent identity before reconciliation. Large manifests spill
to a temporary file while downloading. A transfer failure retains the previous
installed inventory.

There is no total package-count ceiling for negotiated paged inventories.
The frozen inline v1 contract retains its 256-item bound for legacy clients;
larger signed documents require the `paged-inventory-v1` extension. Legacy
clients retain their previous inventory until upgraded. HTTP response-size,
individual archive and authorization checks remain in force.

## Independent package progress

Managed Codex, Hermes and OpenClaw adapters also advertise `independent-items-v1`.
Each package is installed, verified and selected independently. Durable receipts
checkpoint each item; restarting resumes incomplete work. A temporary failure
retries only that item. A terminal rejection requires a corrected signed source
or targeted operator retry. A failed update preserves its previous selection.
Package collisions reject only the incoming package. Removing unrelated packages
is never an implied side effect of a partial update.

The runtime stores packages in separate directories under its managed skill
root. Existing atomic layouts require a separate migration before enabling this
mode. Legacy clients retain their previous protocol. Per-package runtime proof
binds the exact release, hash and nonce to the observed runtime inventory, which
may legitimately differ from the complete desired inventory. Availability and
runtime attestation are separate: a package is not declared verified active
until its real runtime supplies proof. Rejected receipt batches isolate the
affected attempt and allow unrelated receipts to upload.

## Independent package progress

With independent-items-v1, each package has durable installation and activation checkpoints. A retryable failure retries only that package. A terminal failure awaits a corrected target or targeted retry. Healthy packages remain selected and failed updates retain the previous version. Each package requires its own real runtime proof; installation alone is not proof of use. A missing or unreadable package is omitted from observed inventory without preventing healthy peers from being inspected or updated. Rejected receipt batches are isolated by attempt.

Nonempty legacy atomic layouts require explicit migration. Unsupported adapters continue using their existing contract; the extension does not silently change them.
