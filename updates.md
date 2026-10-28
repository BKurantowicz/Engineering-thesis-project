# Updates

## Unreleased

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
