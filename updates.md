# Updates

## Unreleased

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
