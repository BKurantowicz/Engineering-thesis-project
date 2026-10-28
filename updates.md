# Updates

## Unreleased

### 2026-10-28 — Readable Settings dropdowns (US-17-01, #20)

- Restrict the Settings card background selector to the card itself so popup
  item views no longer inherit a stale dark background after a theme change.
- Remove Settings' local combo colors and provide popup text, selection, and
  hover colors through the existing shared ThemeManager palette.
- Use a styled item delegate so selected options paint the shared theme colors.
- Keep all four dropdowns, their settings bindings, and the four-page layout.
- Add isolated offscreen coverage for both languages, all font sizes, repeated
  theme switches, actual palette contrast and rendered selection colors,
  keyboard/mouse input, and reopening.
- Document current dropdown behavior in README.

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
