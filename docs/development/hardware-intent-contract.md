# HardwareIntentContract v1 — bounded typed core (#941)

This first tranche introduces a **pure Python** v1 contract model and a checked-in JSON Schema under the Python project package. It does **not** replace ProjectDesignIntent or the existing project-spec import/review workflow. A design-spec record is **not** automatically treated as an authoritative verification contract.

## Identity and provenance

- Schema version is fixed at 1; contract_id and requirement_id are caller-supplied stable keys, not generated from prose or target positions. contract_version changes explicitly when requirements change.
- The contract requires an explicit target selector (applicability.kind and key), severity and release_blocking flag. Non-informational contracts require a verification-method reference and one or more evidence classes; neither is inferred.
- Embedded waivers require a matching **contract ID and version**, explicit approval identity, approval-evidence reference and reason. A revision mismatch fails validation. This validates metadata binding, not authenticity of approval.
- Unknown fields/units or missing mandatory values are rejected. Informational contracts may omit verification but cannot block release; blocking severity always blocks release.

## Supported dimensional values

- Supported exact-decimal dimensions: voltage (V, mV), current (A, mA), resistance (ohm, kohm), length (mm, um), time (ps, ns), frequency (Hz, kHz, MHz). Unknown units and cross-dimensional comparisons fail closed.
- quantity_range accepts at least one bound. Bounds are inclusive by default; equal endpoints require both inclusive flags to be true.
- nominal_tolerance requires **exactly one** same-dimension absolute tolerance or relative percentage (0..100). Relative tolerance uses absolute nominal magnitude so negative values do not reverse the interval. Range and tolerance cannot both be set.
- The model does not interpret regulatory conformance, physics, natural-language numeric claims or arbitrary units. The JSON Schema covers structure; runtime validators enforce cross-field semantics.

## Engineering Graph links

The link_hardware_intent_contract(graph, contract, provenance=...) function requires matching Requirement and target entities **before** adding an IntentContract node. It adds Requirement → IntentContract (references) and IntentContract → target (applies_to) edges, preserving impact/dependency queries. No Requirement or target is invented. Re-linking the same record is idempotent; conflicting revisions are rejected instead of replacing the canonical ID.

Graph v1 has no region entity. A region selector is valid contract metadata but **cannot** be linked to Graph v1 without a real entity mapping; the function rejects it.

## Conservative design-spec adapter

The pure `adapt_explicit_design_spec_contracts(resolution, bindings)` adapter accepts a persisted `ProjectSpecResolution` and reviewer-authored `ContractConversionBinding` records. It reads **only** the `explicit` spec: the merged `resolved` view may contain inferred PCB heuristics and must not create authoritative requirements.

V1 conversion supports explicit, named power-rail voltage/current maximum and unique interface impedance/skew maximum. The source scalar is converted into a typed exact-decimal quantity. No contract is created unless stable IDs, revision, explicit target applicability, severity, release-blocking policy and required verification/evidence are supplied. Nominal values additionally need an **authored** absolute or percentage tolerance: the existing legacy power-rail `tolerance_pct=5` default is **not** silently used. Maximum-only values produce an explicit upper-bound range, not an invented nominal.

Missing or ambiguous data yields `ContractConversionResult.unresolved` records containing source references and machine-readable reason strings, rather than a silent guess. Repeated source names/kinds and duplicated contract IDs are refused. Reviewer-provided waiver metadata is revalidated for exact contract revision.

This adapter is in-memory and does not mutate KiCad project files, automatically approve waivers, invent graph Requirement nodes, or silently promote inferred data. Conversion and graph linking are separate steps, so missing graph entities still fail closed.

## Remaining before #941 closure

Pass live repository format/type/architecture/unit/integration/security/coverage gates, confirm schema/fixture parity, review all PR threads and warnings, and ensure covered reference-board requirements are represented. Broader source fields, evidence freshness (#942), native canaries (#943), and persistent caches (#944) remain independent follow-ups.
