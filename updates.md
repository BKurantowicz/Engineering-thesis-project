# Updates

## Unreleased

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
