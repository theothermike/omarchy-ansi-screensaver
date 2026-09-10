# ANSI Screensaver for Omarchy

A screensaver that turns Omarchy's `ttfx` terminal animations into a slideshow of
classic and modern **ANSI/ASCII scene art** — with a gallery to manage the pieces,
browsers for the public art archives, and a bar icon.

- Every piece is revealed by one of 33 `ttfx` effects (the art keeps its own
  colours) **or** drawn at emulated modem speed the way a BBS would have shown it;
  tall pieces scroll; a credit caption shows title / artist / group / year; then
  one of seven out-transitions (fade, dissolve, wipe, Doom-melt, curtain, glitch,
  blocks) clears the screen for the next piece.
- Ships with a curated set of bundled pieces (see `ATTRIBUTION.md`) and lets you
  add more from **16colo.rs**, **Demozoo**, the **Internet Archive**, **GitHub
  repositories** (preconfigured: the sixteencolors archive mirror), any **HTTP
  directory index** (preconfigured: artscene.textfiles.com), **asciiart.eu** and
  **ascii.co.uk** — or from local files, folders, zips and URLs.
- Takes over Omarchy's idle screensaver without touching the stock one: its own
  idle timer fires a couple of seconds before Omarchy's, whose launcher then sees
  the running window and stands down; lock, wake and stay-awake keep working.

## Screenshots

| | |
|---|---|
| ![Gallery](docs/gallery.png) The library gallery: thumbnails with per-card preview / star / enable / remove, search, filters, sort. | ![Sources](docs/sources-16colors.png) Browsing a 16colo.rs pack — thumbnails from the archive, Add / Add all. |
| ![Sources with ratings](docs/sources-asciiart.png) asciiart.eu with view/like counts, rating sort and the random-import row. | ![Effects](docs/effects.png) Effects: reveal mix, the ttfx effect set with measured durations, out-transitions. |
| ![Settings](docs/settings.png) Settings: slideshow timing, display/font, Omarchy idle timeouts, takeover. | |

The screensaver itself (art credits in the captions; both pieces are on 16colo.rs):

![Screensaver](docs/screensaver-ultimate-warrior.png)
*"the ultimate warrior" — xeR0 / Blocktronics, 2020, mid-reveal.*

![Screensaver with caption](docs/screensaver-night-city-group.png)
*"Night City Group" — ACiD Productions, 1997, scrolled to the end with the credit caption; IBM VGA font.*

## Requirements

- Omarchy 4.x (Quickshell shell, Hyprland) with its stock `ttfx` and `ghostty` packages.
- Python 3.12+ (standard library only). Optional: `python-pillow` (thumbnails and previews),
  `bsdtar`/libarchive (LHA/ARJ archives from older packs — installed on Omarchy by default).
- No sudo or pkexec is required. Nothing runs as root.

Everything the plugin writes lives in `~/.config/omarchy/ansi-screensaver/`,
`~/.cache/ansi-screensaver/`, `~/.local/state/ansi-screensaver/` and, only when
you ask for it, `~/.local/bin/ansi-screensaver` (symlink) and
`~/.local/share/fonts/ansi-screensaver/` (the VGA font). It never edits your
Omarchy configuration except through Omarchy's own commands: enabling the bar
widget (`omarchy plugin enable`) and, if you change them in Settings, the idle
timeouts in `shell.json` via `omarchy-shell-config`.

## Install

```sh
omarchy plugin add https://github.com/theothermike/omarchy-ansi-screensaver.git --enable
~/.config/omarchy/plugins/io.github.theothermike.ansi-screensaver/bin/ansi-screensaver install --fonts --seed
```

`install` symlinks the CLI to `~/.local/bin/ansi-screensaver`, installs the vendored
IBM VGA font for the user (optional but recommended — 1:2 cells, authentic block
glyphs) and seeds the bundled art into the library (from `art/` when present,
otherwise by fetching the pieces listed in `catalog.json` from 16colo.rs).
If `--enable` did not place the bar icon, run
`omarchy plugin enable io.github.theothermike.ansi-screensaver --section right`.

## Remove

```sh
ansi-screensaver stop --previews                      # if it is running
omarchy plugin remove io.github.theothermike.ansi-screensaver --yes
rm -f ~/.local/bin/ansi-screensaver
rm -rf ~/.config/omarchy/ansi-screensaver ~/.cache/ansi-screensaver ~/.local/state/ansi-screensaver   # library, caches, log
rm -rf ~/.local/share/fonts/ansi-screensaver && fc-cache -f                                            # only if you installed the VGA font
```

Omarchy's stock screensaver and idle service were never modified and take over
again immediately. If you added the optional menu override or keybindings (below),
delete those lines yourself.

Optional integration (what this checkout uses):

- `~/.config/omarchy/extensions/omarchy-menu.jsonc` — override `system.screensaver`
  with `ansi-screensaver launch --force` and add a gallery entry running
  `omarchy-shell ansisaver open`.
- `~/.config/hypr/bindings.lua` — `SUPER+ALT+S` opens the gallery,
  `SUPER+ALT+SHIFT+S` launches the screensaver.

## Using it

**Bar icon** — left click: gallery · right click: launch now · middle click:
toggle idle takeover. The dot badge shows takeover is armed; the icon dims when
Omarchy's screensaver-off toggle or stay-awake is set.

**Gallery** (`omarchy-shell ansisaver open`) — four tabs:

| Tab | What you do there |
|---|---|
| Gallery | thumbnails of the library; search, filter, sort; hover for a full render; enable/disable, star, remove, preview; import files/folders/zips/URLs |
| Sources | one tree browser for every art source: open packs/categories, see thumbnails or text previews (**Preview all** renders the rest on demand), **Add** a piece or **Add all** of a pack; **Random import** N pieces from this source or all of them (walks each catalogue at random, never repeats a pick), or the **highest rated** where a source has ratings (asciiart.eu likes/views — build its rating index once); sort by rating; add your own GitHub repos / HTTP indexes |
| Effects | which ttfx effects and out-transitions play (weights in `config.json`), reveal mix (ttfx vs. baud), colour handling, baud rate, speed; right-click an effect to preview it |
| Settings | hold time, scroll speed, order, caption, columns, font, multi-monitor, **Omarchy's idle timeouts** (screensaver / lock, preset dropdown or exact seconds — written to `shell.json` through `omarchy-shell-config`), idle takeover (+ a 10 s test), maintenance |

Keys: arrows/hjkl browse · Enter preview · `e` enable · `f` favourite · `a` add
(Sources) · `/` search · Tab/Ctrl+1-4 switch tab · Esc close.

**Screensaver** — any key or mouse movement ends it (also focus loss and the
lock screen). `ansi-screensaver launch --force` starts it now, `stop` ends it,
`preview <id>` shows one piece on the focused monitor.

## Sources

The Sources tab shows one tree browser for every archive. Pick a source on the
left, open folders/packs, and use **Add** on a piece or **Add all** on a pack.
Items show the archive's thumbnail when it has one, the text itself for pure
ASCII sites, or a **Preview** button; **Preview all** (or `p`) renders every
pictureless item on the page one by one. `a` adds the selected item, `Enter`
opens/previews, `Backspace` goes up, `/` searches where the source supports it.

| Source | What it is | Browse by | Thumbnails | Ratings |
|---|---|---|---|---|
| **16colo.rs** | the ANSI/ASCII art archive: every artpack since 1990 (JSON API) | year → pack, group, artist, latest, search | yes | no |
| **Demozoo** | demoscene database: ANSI / ASCII / ASCII-collection / artpack productions | type, search; files via scene.org | per item | no |
| **Internet Archive** | search-driven: items → files → archive members | preset queries or free search | item image | no |
| **GitHub repositories** | any repo (the sixteencolors archive mirror is preconfigured) | folders → archives → members | via 16colo.rs for the mirror | no |
| **HTTP directory indexes** | plain listings such as artscene.textfiles.com (preconfigured) | folders → files/archives | when the site has `.png` renders | no |
| **asciiart.eu** | the ASCII Art Archive (categories of classic ASCII) | category → subcategory → piece | text preview | **likes + views** |
| **ascii.co.uk** | topic pages of ASCII art | topic → piece | text preview | no |

Add your own GitHub repository or HTTP index with **Add source…** (or
`ansi-screensaver sources add --kind github_repo|http_index --url …`).
Packs in `.zip`, `.lha`/`.lzh` and other archive formats are opened with
libarchive; 16colo.rs pieces are fetched individually so no pack download is needed.

**Random import** — the row above the grid imports *N* random pieces from the
current source or from all of them (each source walks its own catalogue at
random: a random year → pack → file on 16colo.rs, a random page on Demozoo, a
random category on asciiart.eu…). Picks are remembered in
`~/.cache/ansi-screensaver/sources/random-history.json` so you never get the
same piece twice, and imports carry a `random` tag. **Highest rated** works for
sources with ratings — currently asciiart.eu — after you build its rating index
once (**Build rating index**, a few minutes: it records likes/views for every
piece on the site); picks are then sampled from the top tenth by score.

Everything imported keeps its credits: SAUCE title/artist/group/date when the
file has them, the archive's own metadata otherwise, plus the source URL and a
licence note in `meta.json`. The bundled starter set (`catalog.json`) is
fetched from 16colo.rs on first run and listed with full credits in
`ATTRIBUTION.md`; the artwork remains its artists' property.

## CLI

```
ansi-screensaver launch [--force] [--piece ID] [--effect NAME|baud] [--once] [--dry-run]
ansi-screensaver stop [--previews] | preview [ID | --random] [--effect NAME]
ansi-screensaver library list|show|enable|disable|favorite|unfavorite|remove ID
ansi-screensaver import <file|dir|zip|url>... [--encoding cp437|latin1|utf8] [--wrap pending]
ansi-screensaver sources list|add --kind github_repo|http_index --url ...|remove ID
ansi-screensaver browse --source ID [--path SEG]... [--search Q] [--page N] [--details]
ansi-screensaver add --source ID --entry EID [--all]     preview --source ID --entry EID
ansi-screensaver random --count N [--source ID | --all] [--top]      index build|status --source ID
ansi-screensaver idle get | set [--screensaver S] [--lock S]        # Omarchy's own timeouts (shell.json)
ansi-screensaver config get|set|dump    doctor [--network]    snapshot    seed    thumbs
ansi-screensaver fonts install|status   install [--fonts] [--seed]
ansi-screensaver fetch [--catalog F] [--into DIR]   curate --packs ...   bundle   attribution   (dev)
```

Add `--json` for machine-readable output and `--progress` to stream
`progress n/total label` lines on long jobs. IPC (`omarchy-shell ansisaver <fn>`):
`open`, `openTab <tab>`, `launch`, `stop`, `preview [id]`, `toggleTakeover`,
`refresh`, `status`, `armTest <seconds>`, `disarmTest`, `set <key> <json>`,
`setIdle screensaver|lock <seconds>`, `library <action> <id>`.

## Files

| Path | Purpose |
|---|---|
| `~/.config/omarchy/ansi-screensaver/config.json` | settings (`config dump` shows every key) |
| `~/.config/omarchy/ansi-screensaver/library/<id>/` | `original.*`, `meta.json`, `flat.ans` (normalised), `render.png`, `thumb.png` |
| `~/.cache/ansi-screensaver/` | source API responses, downloaded packs, previews, font-size calibration |
| `~/.local/state/ansi-screensaver/runner.log` | what the slideshow did |
| `catalog.json`, `ATTRIBUTION.md` (repo) | the curated starter set (fetched on first run) and its credits |

## How it works

`.ans` files are full of cursor movement, iCE colours and CP437 bytes that `ttfx`
cannot take, so the engine interprets each file into a cell grid (SAUCE, CP437 /
Latin-1 / UTF-8, wrap at the SAUCE width, iCE, erase-with-background) and writes
a `flat.ans` of plain 24-bit SGR rows in the VGA palette — which `ttfx` animates
faithfully with `--existing-color-handling always`. The runner sizes ghostty so 80
columns fill the monitor (self-calibrating after the first run), pins the piece with
an invisible anchor so effects place it exactly, and draws captions, scrolling and
out-transitions itself.

Development: the shell hot-reloads QML on save (`omarchy-shell shell rescanPlugins`
to force; `rm -rf ~/.cache/quickshell/qmlcache && omarchy restart shell` when stale);
logs in `journalctl --user -t omarchy-shell`. Tests: `python3 -B -m unittest discover -s tests`.

## Credits

Art: see `ATTRIBUTION.md` — the pieces belong to their artists; SAUCE credits are
preserved and shown. Font: Px437 IBM VGA 8x16 from the Ultimate Oldschool PC Font
Pack (CC BY-SA 4.0). Effects: [ttfx](https://github.com/omacom-io/ttfx) (MIT).
