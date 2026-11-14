# Bundled fonts for botyaraMC

| File | Family | Purpose | License |
|---|---|---|---|
| `Inter-Regular.ttf`, `Inter-Bold.ttf` | Inter | UI (single interface font) + banner SVG | [OFL-Inter.txt](OFL-Inter.txt) |
| `JetBrainsMono-Regular.ttf`, `JetBrainsMono-Bold.ttf` | JetBrains Mono | Logs and crash reports (monospace, Cyrillic support) | [OFL-JetBrainsMono.txt](OFL-JetBrainsMono.txt) |

Both families are distributed under the **SIL Open Font License 1.1** — they can be freely
bundled with software. When the launcher starts, the fonts are loaded without system-wide installation
(Windows/macOS — within the process, Linux — the user directory `~/.local/share/fonts/botyaraMC`).

Source provenance:
- **JetBrains Mono** — official repository [JetBrains/JetBrainsMono](https://github.com/JetBrains/JetBrainsMono) (fonts/ttf, master).
- **Inter 4.1** — official release [rsms/inter v4.1](https://github.com/rsms/inter/releases/tag/v4.1):
  static weights `Regular` (wght=400) and `Bold` (wght=700) are obtained from the official
  `InterVariable.ttf` via `fonttools varLib.instancer --update-name-table … wght=… opsz=14`,
  then the name-tables are normalized (`Inter` / `Regular` / `Bold`). The OFL allows modifications
  and bundling while preserving this license.
