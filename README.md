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

## Install

```sh
omarchy plugin add git@github.com:theothermike/omarchy-ansi-screensaver.git   # or clone into ~/.config/omarchy/plugins/<id>
omarchy plugin enable io.github.theothermike.ansi-screensaver --section right # bar icon; also enables the service + overlay
~/.config/omarchy/plugins/io.github.theothermike.ansi-screensaver/bin/ansi-screensaver install --fonts --seed
```

`install` symlinks the CLI to `~/.local/bin/ansi-screensaver`, installs the vendored
IBM VGA font for the user (optional but recommended — 1:2 cells, authentic block
glyphs) and seeds the bundled art into the library. Requirements: Omarchy with
`ttfx` and `ghostty` (both stock), Python 3.12+; `python-pillow` for thumbnails.

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
| `art/` (repo) | the bundled pieces, `catalog.json`, `ATTRIBUTION.md` |

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
