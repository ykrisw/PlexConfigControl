# Approved panel appearance

`approved-panels.html` is the exact latest user-approved conversation preview,
including the final 30% shield reduction. It is a host-rendered HTML fragment,
not the installed application's entry point. Its sample archives, history and
operation scenarios must never be connected as fabricated production results.

The production appearance rules are in
`plexconfigcontrol/static/approved-appearance.css`, imported by both the shared
panel layout and standalone Restore view.

- Five equally sized tabs and shared content geometry; existing 18px insets.
- Main cards expand downwards; lists fill the remaining card height and scroll.
- Header shield: fixed 21 × 23.1 CSS px, non-shrinking.
- Yellow notification/dialog borders: 3px; background follows the theme.
- Scrollbars: 23.52px in engines supporting explicit scrollbar sizing;
  other engines use their native width. Track/thumb padding scale together.
- Plex and Language strips: 56px. Plex Server/Language retain their original
  typography: the attempted RUNNING-style change was reverted.
- Backup creation and Archive Validation headings match Appearance (20px/600).
- Important is compact; Existing Backups receives the freed vertical space.
- Light content text is black. Text on dark controls/header stays white.
- Unchecked selectors: white in Light, card-coloured in Dark; selected green
  with a subtle blue row background appropriate to the active theme.
- Account group centred at 40% of its card height; title shifted up another
  5% of card height and ACTIVE shifted down 5%. Photo diameter: 188.9085px.
- Settings information block centred vertically, preserving label/value columns.
- Default application theme remains System; English/Polish selection persists.

Approval of this appearance does not establish implementation or end-to-end
verification of every operation shown in the preview. Dashboard account actions
and Plex status are connected; profile photo management remains pending.
Backup, History and Settings content integration is still incomplete.
