# Application Updates

This file records application and documentation changes. The [README](README.md)
describes the current application. Add a dated **Unreleased** entry in every
change delivery, with its behavior or technical impact and issue/story reference.
Existing commit references can be added once they are known. Keep uncommitted
work under Unreleased; do not describe planned work as completed or invent release
versions. Commits and merges alone do not establish that a release occurred.

## Unreleased

### 2026-10-27 — Traceable change history (US-7-02, #24)

- Reconstruct application and documentation history from the 26 non-merge commits
  reachable from `df175c48dfc9f74d14e0559de4c9d08f28e99899`, with verifiable source
  links and commit dates.
- List nine merge integrations separately, avoiding duplicate implementation
  entries and preserving the company-address delivery from PR #21.
- Document ongoing update-entry conventions and link them from README.

This entry records documentation work. Unmerged story branches and unrelated
local application edits are not presented as completed history. Historical
summaries are not claims of passing tests, leader approval, or release status.

## Historical changes

Dates below come from the commits in the repository. Entries summarize changes
supported by their messages, changed files, and inspected source/diffs; they are
not retroactive release notes or claims that the functionality passed testing.
Merge commits integrate these changes and are listed separately to avoid
counting the same implementation twice.

### 2026-10-22 — Company address persistence (US-17-02, #17)

- Replaced the combined company-address input with separate Street, Postal Code,
  and City fields bound to the existing `company_info` JSON keys. Repeated saves
  no longer append the postal code and city to the street.
- Kept existing address text intact until the operator explicitly edits it,
  allowing manual correction of previously duplicated text without guessing.
- Added English and Polish labels while preserving the four Settings pages and
  existing theme integration.
- Added isolated configuration and offscreen Qt regression tests for persistence,
  edits, reopening, missing address components, localization, and theme settings.
- Documented the current form behavior, manual correction, and test command in
  `README.md`.

Source: [29ef9bf](https://github.com/BKurantowicz/Engineering-thesis-project/commit/29ef9bf), delivered in [PR #21](https://github.com/BKurantowicz/Engineering-thesis-project/pull/21).

### 2026-10-17 — Order data and retrieval

- Extended order and invoice address data and introduced a separate `packages`
  table with order/package references, tracking number, actual weight, and
  creation time.
  [6995b60](https://github.com/BKurantowicz/Engineering-thesis-project/commit/6995b60)
- Added recipient name fields for orders and billing name fields for invoices;
  revised the related README documentation.
  [bf93f41](https://github.com/BKurantowicz/Engineering-thesis-project/commit/bf93f41)
- Expanded OrderController queries with delivery fields, date filtering, text
  search, sorting, and row-based results; updated order creation to accept
  delivery details.
  [f0bfc7a](https://github.com/BKurantowicz/Engineering-thesis-project/commit/f0bfc7a)
- Revised comments in OrderController.
  [ef6c571](https://github.com/BKurantowicz/Engineering-thesis-project/commit/ef6c571)

### 2026-10-11 — Dashboard, configuration, and themes

- Introduced DashboardView and DashboardController and connected dashboard data
  retrieval to the database.
  [c508a1c](https://github.com/BKurantowicz/Engineering-thesis-project/commit/c508a1c)
- Reorganized translation files under `utils/`, added dashboard translations, and
  revised dashboard/main-window code and comments.
  [e398bd9](https://github.com/BKurantowicz/Engineering-thesis-project/commit/e398bd9)
- Refined dashboard presentation, translations, and data-query logic, with
  corresponding README changes.
  [db3a8d1](https://github.com/BKurantowicz/Engineering-thesis-project/commit/db3a8d1)
- Expanded project documentation.
  [b01d29a](https://github.com/BKurantowicz/Engineering-thesis-project/commit/b01d29a)
- Adjusted order-status chart counting logic in DashboardController.
  [36e57e9](https://github.com/BKurantowicz/Engineering-thesis-project/commit/36e57e9)
- Introduced SettingsView, SettingsController, and settings translations;
  expanded nested JSON configuration and adapted startup and translation loading.
  [d43d8b7](https://github.com/BKurantowicz/Engineering-thesis-project/commit/d43d8b7)
- Added ThemeManager with Dark, Light, and Modern palettes and applied the shared
  stylesheet at startup and after settings changes. Existing local styles were
  still present in other views.
  [365c0a5](https://github.com/BKurantowicz/Engineering-thesis-project/commit/365c0a5)
- Updated documentation for configuration and theming.
  [09e136e](https://github.com/BKurantowicz/Engineering-thesis-project/commit/09e136e)

### 2026-10-10 — Database-backed order browsing

- Connected OrdersView to a new OrderController, replacing its embedded mock
  order rows with database retrieval.
  [877a135](https://github.com/BKurantowicz/Engineering-thesis-project/commit/877a135)
- Revised order filtering and associated view/controller/schema code.
  [c2ff112](https://github.com/BKurantowicz/Engineering-thesis-project/commit/c2ff112)
- Added an MVC illustration and updated the README.
  [ecb9bcf](https://github.com/BKurantowicz/Engineering-thesis-project/commit/ecb9bcf)
- Clarified the README's project structure.
  [e874b55](https://github.com/BKurantowicz/Engineering-thesis-project/commit/e874b55)

### 2026-10-05 — Documentation

- Expanded the README's project and database documentation.
  [f8ca10b](https://github.com/BKurantowicz/Engineering-thesis-project/commit/f8ca10b)

### 2026-10-04 — Initial structure and order UI

- Added the initial project documentation and MVC architecture description.
  [91f9896](https://github.com/BKurantowicz/Engineering-thesis-project/commit/91f9896)
- Renamed `project_documentation.md` to `README.md`.
  [e0a53bb](https://github.com/BKurantowicz/Engineering-thesis-project/commit/e0a53bb)
- Added the database initialization module and initial ignore rules.
  [c1f3ed8](https://github.com/BKurantowicz/Engineering-thesis-project/commit/c1f3ed8)
- Corrected the ignore-file name to `.gitignore`.
  [c4ab414](https://github.com/BKurantowicz/Engineering-thesis-project/commit/c4ab414)
- Added application startup/main-window code, JSON configuration, and translation
  loading, together with updated ignore rules.
  [63d11fc](https://github.com/BKurantowicz/Engineering-thesis-project/commit/63d11fc)
- Introduced the initial OrdersView and its translations and navigation.
  [bc988d5](https://github.com/BKurantowicz/Engineering-thesis-project/commit/bc988d5)
- Adjusted the order-count filter and order-view translations.
  [f8b8f5c](https://github.com/BKurantowicz/Engineering-thesis-project/commit/f8b8f5c)
- Added pick-list tables to the database schema and adjusted related translations
  and ignore rules. This added storage structures, not a pick-list execution UI.
  [9cdf9b1](https://github.com/BKurantowicz/Engineering-thesis-project/commit/9cdf9b1)

### Integration history

| Date | Merge | Integrated work |
| --- | --- | --- |
| 2026-10-04 | [cc17832](https://github.com/BKurantowicz/Engineering-thesis-project/commit/cc17832) | Initial master-branch history. |
| 2026-10-04 | [a7ff96e](https://github.com/BKurantowicz/Engineering-thesis-project/commit/a7ff96e) | Orders-view branch, PR #1. |
| 2026-10-05 | [1d67b90](https://github.com/BKurantowicz/Engineering-thesis-project/commit/1d67b90) | Database-related branch, PR #2. |
| 2026-10-10 | [ad45265](https://github.com/BKurantowicz/Engineering-thesis-project/commit/ad45265) | Database-backed order work, PR #3. |
| 2026-10-11 | [fead76d](https://github.com/BKurantowicz/Engineering-thesis-project/commit/fead76d) | Dashboard branch, PR #4. |
| 2026-10-11 | [8d2b78f](https://github.com/BKurantowicz/Engineering-thesis-project/commit/8d2b78f) | Settings and themes, PR #13. |
| 2026-10-17 | [f685a47](https://github.com/BKurantowicz/Engineering-thesis-project/commit/f685a47) | Package and address schema changes, PR #16. |
| 2026-10-17 | [ddeab90](https://github.com/BKurantowicz/Engineering-thesis-project/commit/ddeab90) | Order-controller changes, PR #18. |
| 2026-10-22 | [df175c4](https://github.com/BKurantowicz/Engineering-thesis-project/commit/df175c4) | Company-address persistence, PR #21. |
