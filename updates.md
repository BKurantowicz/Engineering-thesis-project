# Updates

## Unreleased

### 2026-11-01 — Capacity-safe physical placements (US-8-02, #26)

- Check current physical occupancy and both rack limits inside each stock write
  transaction. Permit exactly 100%; reject partial writes, missing measurements,
  invalid limits, and virtual placement targets.
- Identify the failing constraint and suggest only physical racks fitting the
  complete addition. Recheck every occupied rack after product measurement edits.
- Cover boundaries, alternatives, rollback, and competing placements with tests.

### 2026-11-01 — Product search and saleable quantities (US-14-01, #32)

- Replace the Products placeholder with a translated/themed catalogue, stable
  row identities, physical/reserved/saleable quantities, locations, and status.
- Search SKU and both names case-insensitively; combine physical-rack scope and
  inclusive quantity/price ranges with AND, with clear invalid/empty states.
- Exclude virtual stock and reservations from saleable quantities; show inactive
  products with zero saleable quantity while retaining physical/reserved values.

### 2026-11-01 — Validated product maintenance (US-14-02, #33)

- Add translated Add/Edit forms with required SKU/names and non-negative prices
  of at most two decimal places, optional descriptions and catalogue measurements.
- Enforce case-insensitive SKU uniqueness in a serialized write transaction;
  surface legacy collisions without merging or deleting records.
- Preserve identities, historical item quantities/prices, and stock. Route stored
  measurement edits through capacity validation and rollback failed/cancelled saves.

### 2026-11-01 — Product retirement with history protection (US-14-03, #34)

- Add repeatable active-state migration and Deactivate/Reactivate/Delete actions.
- Block referenced-product deletion through controller checks and database triggers;
  retain inventory, movements, orders, allocations, and shortage history.
- Reject new order-item selections of inactive products while allowing existing
  orders and their picking work to continue.

### 2026-11-01 — Explicit rack stock additions (US-14-04, #35)

- Add positive whole quantities to product/location inventory pairs through an
  explicit form; never replace totals or duplicate catalogue records.
- Require positive physical measurements and use the common capacity guard for
  every addition. Save movement logs atomically and refresh quantities/capacity.

### 2026-11-01 — Pick-list generation and reservations (US-10-01, #27)

- Select eligible NEW/IN_PROGRESS orders and atomically store lists, order links,
  allocations, and reservations without deducting physical stock.
- Recheck eligibility and shared availability at save time; exclude orders on
  open lists and already fully picked orders awaiting packing.

### 2026-11-01 — Manual source allocations (US-10-02, #28)

- Show order identity, SKU/name, demand, physical racks, and available-to-pick
  quantities. Support split sources with exact per-item demand totals.
- Persist chosen sources without recomputing them on ordinary reopening; exclude
  virtual braki and retain per-order traceability for shared products.
- Keep route optimization outside the workflow.

### 2026-11-01 — Persistent picking and closure (US-10-03, #29)

- Start lists and transition NEW orders to IN_PROGRESS. Confirm cumulative picked
  totals, deduct only their increase, consume reservations, and log physical moves.
- Reject excess/reversed totals; repeated confirmation/reopening is idempotent.
- Close only picked/resolved lists, preserving history without marking orders
  packed or shipped. Refresh the catalogue, dashboard, and order browser.

### 2026-11-01 — Chronological shortage reconciliation (US-10-04, #30)

- Record the actual missing difference once at virtual braki with product, source,
  list, and operation identity; expose a missing-stock history view.
- Reconcile affected open lists together, oldest order/date-ID first, retaining
  complete feasible orders and cancelling unfillable orders with a reason.
  Preserve reservations of unaffected lists and continue with later orders.
- Return existing picked goods under both capacity limits, splitting returns over
  physical racks when necessary. Never return missing goods or duplicate returns.
- Commit counts, reservations, cancellations, replacement allocations, returns,
  and events together; roll back when returns cannot fit or data is invalid.
- Reject stale physical-count forms and preserve previous allocation snapshots.

### 2026-11-01 — Coherent demonstration data (US-10-05, #31)

- Add an explicit seed command creating realistic products, customers, racks,
  stock, orders, and open/partial/closed/shortage-cancelled list examples through
  the real controllers.
- Build the dataset in a temporary database before replacing a designated mock
  target; never seed destructively during startup.
- Require an explicit replacement flag for existing files and reject SQLite
  sidecars. Test repeatability, capacity, references, and failure preservation.

### 2026-11-01 — Integrated documentation and validation

- Document current catalogue, stock, picking, shortage, seed, and migration
  behavior; remove placeholder screenshots and unsupported feature claims.
- Update architecture and the complete initialized schema while preserving
  company-address, customer, database-path, and theme documentation.
- Add isolated controller/concurrency/dialog regressions and adapt the older
  capacity corruption fixture to the new product-deletion protection.

### 2026-11-01 — Search customer contact records (US-15-01, #36)

- Add translated, case-insensitive customer search across email, first/last name,
  and city, including inactive records and literal punctuation.
- Preserve the search during maintenance actions, clear it to restore the full
  list, and distinguish unmatched queries from an empty customer list.
- Keep action targets tied to stable customer IDs after filtering; add isolated
  search, empty-state, and filtered-action regressions and update README.

### 2026-10-28 — Customer lifecycle with preserved order history (US-15-03, #38)

- Add repeatable active-state migration and translated Activate/Deactivate/Delete
  actions, with visible status and stable selected-customer identity.
- Confirm physical deletion and allow it only for customers without orders;
  explain blocked deletion and preserve historical relationships.
- Reject new orders for inactive customers in the controller and database while
  keeping existing order reads, updates, and fulfillment unblocked.
- Preserve saved inactive state on restart and contact edits; add database deletion
  protection independent of SQLite connection foreign-key settings.
- Add isolated migration, rollback, history, write-path, and UI regressions;
  update the existing phone migration assertion and README behavior/schema.

### 2026-10-28 — Customer contact and address maintenance (US-15-02, #37)

- Add a reachable Customers list and translated/themed Add/Edit forms using the
  configured database and stable record identities.
- Require names and address components; accept optional phone/email and validate
  supplied email structure. Store blank optional contacts as absent values.
- Enforce case-insensitive email uniqueness within each write transaction,
  including simultaneous application saves. Report legacy collisions without
  automatically rewriting, merging, or deleting existing records.
- Add the nullable phone column through a repeatable, non-destructive migration.
- Preserve historical delivery/billing details and order quantities/prices when
  editing customer master data; cancelled or failed saves leave records unchanged.
- Add isolated persistence, migration, concurrency, and form regressions; update
  README behavior/schema documentation.

### 2026-10-28 — Physical weight and volume capacity (US-8-01, #25)

- Replace the hardcoded 10,000-unit denominator and synthetic In picking segment
  with independent kg/m³ indicators for the warehouse or a selected physical rack.
- Calculate decimal usage from stored quantities and product measurements;
  aggregate warehouse percentages against summed rack limits.
- Add repeatable physical/virtual location classification; exclude virtual braki
  stock and limits without deleting existing records or changing quantities.
- Treat unavailable measurements, limits, invalid stock, and read failures as
  unavailable data. Show valid empty racks as 0% and legacy overloads truthfully.
- Refresh current values while preserving the selected rack and trend period.
- Add isolated calculation, migration, and translated/themed UI regressions;
  adapt existing theme/fixture checks and update README behavior/schema details.

### 2026-10-28 — Consistent runtime themes (US-12-01, #12)

- Replace local MainWindow, Orders, Dashboard, and Settings stylesheets with
  semantic object names and centralized Light/Dark/Modern palette rules.
- Apply the shared theme at startup and on Settings Save; refresh existing chart
  backgrounds, axes, labels, legends, series, and slices without replacing data.
- Preserve theme colors after data reloads and for charts created later.
- Keep readable dropdown popup/selection behavior compatible with US-17-01;
  centralize accordion expansion styling and preserve existing interactions.
- Add full-window offscreen regression coverage using isolated configuration and
  databases, and document the runtime theme API and current behavior in README.

### 2026-10-28 — Readable Settings dropdowns (US-17-01, #20)

- Restrict the Settings card selector so dropdown popup views do not inherit
  stale background colors after a theme change.
- Apply readable popup text, selection, and hover colors from the shared theme
  using styled item delegates, preserving all options and settings bindings.
- Cover both languages, all font sizes, repeated theme switches, actual palette
  contrast, rendered selection colors, keyboard/mouse input, and reopening.
- Document the current dropdown behavior in README.

### 2026-10-27 — Current application documentation audit (US-7-01, #23)

- Audited the original screens, startup behavior, architecture, and 17-table
  schema, correcting earlier claims about unfinished workflows and missing
  package relationships.
- Reconciled that audit with subsequent implementations: the current README
  now describes the delivered warehouse/store workflows and all 19 tables.
- Kept the README focused on current behavior; historical changes belong here.

### 2026-10-27 — Consistent database selection (US-BASE-03, #40)

- Pass MainWindow's effective configured database path to OrdersView and its
  OrderController, matching database initialization and Dashboard.
- Preserve the default `warehouse.db`, existing relative/absolute path semantics,
  and configuration keys. Saved path changes take effect after restart.
- Add integration coverage for nondefault files without silent fallback, a
  separate untouched default database, selected-file reads/writes, and restart.
- Document database selection and regression coverage in README.

### 2026-10-25 — Existing-order row contract (US-BASE-02, #39)

- Read order and item values by their SQLite field names, preventing the
  nine-value unpacking failure when the controller returns its current 14-column
  order records. Preserve the existing displayed columns and optional-join defaults.
- Remove the order-loading debug print and retain the current date/limit controls.
- Add real controller/view regression coverage for empty and populated lists,
  item details, repeated reloads, MainWindow startup, and unchanged persisted data.
- Document the current order-browsing behavior and validation scope in README.

### 2026-10-25 — Clean-checkout database import (US-BASE-01, #22)

- Rename the tracked `Models` directory to `models`, matching the existing
  `models.database` import and documented package layout. Database source and
  initialization behavior remain unchanged.
- Add regression coverage for Git-tracked import capitalization, actual entry-point
  startup with isolated configuration and an empty database, and preservation of
  existing database records during initialization.
- Document startup dependencies, the canonical package spelling, and the scope
  of startup regression checks in `README.md`.

### 2026-10-21 — Company address persistence (US-17-02, #17)

- Replace the combined company-address input with separate Street, Postal Code,
  and City fields bound to the existing `company_info` JSON keys. Repeated saves
  no longer append the postal code and city to the street.
- Keep existing address text intact until the operator explicitly edits it,
  allowing manual correction of previously duplicated text without guessing.
- Add English and Polish labels while preserving the four Settings pages and
  existing theme integration.
- Add isolated configuration and offscreen Qt regression tests for persistence,
  edits, reopening, missing address components, localization, and theme settings.
- Document the current form behavior, manual correction, and test command in
  `README.md`.
