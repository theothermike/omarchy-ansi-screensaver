.pragma library

// Pure helpers shared by the overlay tabs.

var TTFX_EFFECTS = ["beams", "binarypath", "blackhole", "bouncyballs", "bubbles", "burn", "colorshift",
  "crumble", "decrypt", "errorcorrect", "expand", "fireworks", "highlight", "laseretch", "matrix",
  "middleout", "orbittingvolley", "overflow", "pour", "print", "rain", "randomsequence", "rings",
  "scattered", "slice", "slide", "smoke", "spotlights", "spray", "swarm", "sweep", "synthgrid",
  "thunderstorm", "unstable", "vhstape", "waves", "wipe"]
var TRANSITIONS = ["fade", "dissolve", "wipe", "melt", "curtain", "glitch", "blocks", "cut"]

function get(obj, path, fallback) {
  var cur = obj
  var parts = path.split(".")
  for (var i = 0; i < parts.length; i++) {
    if (cur === null || typeof cur !== "object" || !(parts[i] in cur)) return fallback
    cur = cur[parts[i]]
  }
  return cur === undefined ? fallback : cur
}

function filterLibrary(lib, search, filter, sort) {
  var q = (search || "").trim().toLowerCase()
  var out = []
  for (var i = 0; i < (lib || []).length; i++) {
    var p = lib[i]
    if (filter === "enabled" && !p.enabled) continue
    if (filter === "disabled" && p.enabled) continue
    if (filter === "favorites" && !p.favorite) continue
    if (filter === "ansi" && p.format !== "ansi") continue
    if (filter === "ascii" && p.format !== "ascii") continue
    if (q !== "") {
      var hay = [p.id, p.title, p.author, p.group, p.pack, (p.tags || []).join(" "), String(p.year || "")].join(" ").toLowerCase()
      if (hay.indexOf(q) === -1) continue
    }
    out.push(p)
  }
  var key = sort || "added"
  function cmp(av, bv) { return av < bv ? -1 : (av > bv ? 1 : 0) }
  out.sort(function(a, b) {
    var r
    if (key === "title") r = cmp((a.title || "").toLowerCase(), (b.title || "").toLowerCase())
    else if (key === "author") r = cmp((a.author || "").toLowerCase(), (b.author || "").toLowerCase())
    else if (key === "year") r = (b.year || 0) - (a.year || 0)
    else if (key === "size") r = (b.rows || 0) - (a.rows || 0)
    else if (key === "rating") r = (b.score || 0) - (a.score || 0)
    else r = cmp(b.added || "", a.added || "")
    // Ties are common (a batch import stamps many pieces with the same second)
    // and the engine's sort is not guaranteed stable, so break them
    // deterministically: the grid must keep its order when a piece is removed.
    return r || cmp(b.added || "", a.added || "") || cmp(a.id, b.id)
  })
  return out
}

function libraryHas(lib, sourceId, entryId, sourceUrl) {
  for (var i = 0; i < (lib || []).length; i++) {
    var p = lib[i]
    if (entryId && p.source_id === entryId) return p.id
    if (sourceUrl && p.source_url && p.source_url === sourceUrl) return p.id
  }
  return ""
}

function fileUrl(path) {
  if (!path) return ""
  return "file://" + path
}

function credits(p) {
  var s = p.author || ""
  if (p.group) s += (s ? " · " : "") + p.group
  if (p.year) s += (s ? " · " : "") + p.year
  return s
}

function pct(n, total) {
  if (!total) return 0
  return Math.max(0, Math.min(1, n / total))
}

function sortEntries(entries, key) {
  var out = (entries || []).slice()
  if (key === "rating") out.sort(function(a, b) { return ((b.meta && b.meta.score) || 0) - ((a.meta && a.meta.score) || 0) })
  else if (key === "title") out.sort(function(a, b) { return (a.label || "").toLowerCase() < (b.label || "").toLowerCase() ? -1 : 1 })
  else if (key === "year") out.sort(function(a, b) { return ((b.meta && b.meta.year) || 0) - ((a.meta && a.meta.year) || 0) })
  // collections first in every order
  out.sort(function(a, b) { return (a.type === "collection" ? 0 : 1) - (b.type === "collection" ? 0 : 1) })
  return out
}
