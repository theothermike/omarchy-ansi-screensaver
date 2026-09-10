import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland

// Headless owner of the plugin state:
//  * the snapshot (library, config, doctor, sources) read from the CLI;
//  * idle takeover: Omarchy's own idle service keeps its job (it launches the
//    stock screensaver, locks, wakes, honours stay-awake); the Hyprland window
//    watcher below sees the stock screensaver window map and has the launcher
//    replace it with ours. Firing our own timer first would not do: launching
//    a screensaver counts as compositor activity, so it would reset Omarchy's
//    idle monitor and postpone the lock. Our IdleMonitor is only a fallback
//    that fires a few seconds after Omarchy's, for when the stock launcher
//    declined (an unsupported default terminal, say);
//  * the `ansisaver` IPC target used by the bar widget, menu and keybinds.
// Every mutation goes through the CLI; the CLI touches a `revision` file that
// the directory watcher below picks up, so the UI never has to poll.
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  readonly property string pluginId: "io.github.theothermike.ansi-screensaver"
  readonly property string home: Quickshell.env("HOME")
  readonly property string pluginDir: home + "/.config/omarchy/plugins/" + pluginId
  readonly property string cli: pluginDir + "/bin/ansi-screensaver"
  readonly property string configDir: home + "/.config/omarchy/ansi-screensaver"
  readonly property string shellJsonPath: home + "/.config/omarchy/shell.json"
  readonly property string togglesDir: home + "/.local/state/omarchy/toggles"
  readonly property string indicatorsDir: home + "/.local/state/omarchy/indicators"
  readonly property string screensaverClass: "org.omarchy.screensaver"
  // ghostty applies `title` from our config file before the window maps, so
  // the openwindow event already tells our windows apart from the stock ones.
  readonly property string ourTitle: "ANSI Screensaver"

  // ---- snapshot ----------------------------------------------------------
  property var snapshot: null
  readonly property var config: snapshot ? snapshot.config : ({})
  readonly property var library: snapshot ? (snapshot.library || []) : []
  readonly property var doctor: snapshot ? (snapshot.doctor || []) : []
  readonly property var sources: snapshot ? (snapshot.sources || []) : []
  readonly property var effects: snapshot ? snapshot.effects : null
  property bool loading: false
  property string lastError: ""
  property string lastEvent: ""
  property bool seedTried: false

  function logEvent(event) {
    root.lastEvent = event
    console.log("ansisaver " + new Date().toISOString() + " " + event)
  }

  function reload() {
    if (root.loading) { reloadDebounce.restart(); return }
    root.loading = true
    snapshotProc.running = true
  }

  Timer { id: reloadDebounce; interval: 300; onTriggered: root.reload() }

  Process {
    id: snapshotProc
    command: [root.cli, "snapshot"]
    environment: ({ PYTHONDONTWRITEBYTECODE: "1" })
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw === "") return
        try {
          root.snapshot = JSON.parse(raw)
          root.lastError = ""
        } catch (e) {
          root.lastError = "could not parse snapshot: " + e
        }
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var err = String(text || "").trim()
        if (err !== "") root.lastError = err
      }
    }
    onExited: function(exitCode) {
      root.loading = false
      if (exitCode !== 0 && root.lastError === "") root.lastError = "snapshot exited " + exitCode
      root.logEvent("snapshot pieces=" + root.library.length)
      if (root.snapshot && root.library.length === 0 && !root.seedTried) {
        root.seedTried = true
        root.runCli(["seed"], {})
      }
    }
  }

  // ---- idle takeover -----------------------------------------------------
  property var shellIdle: ({})
  readonly property int screensaverSeconds: {
    var v = Number(root.shellIdle.screensaver)
    return isFinite(v) && v >= 0 ? Math.round(v) : 150
  }
  readonly property int lockSeconds: {
    var v = Number(root.shellIdle.lock)
    return isFinite(v) && v >= 0 ? Math.round(v) : 300
  }
  readonly property int fallbackSeconds: {
    var v = Number(root.config.idle ? root.config.idle.fallback_seconds : 5)
    return isFinite(v) && v >= 1 ? Math.round(v) : 5
  }
  readonly property bool takeoverEnabled: !!(root.config.idle && root.config.idle.takeover)
  property bool screensaverOff: false
  property bool stayAwake: false
  property bool flagsLoaded: false
  property int testSeconds: 0
  readonly property int timeoutSeconds: Math.max(5, root.screensaverSeconds + root.fallbackSeconds)
  readonly property bool armed: root.flagsLoaded && root.takeoverEnabled && !root.screensaverOff
                                && !root.stayAwake && root.screensaverSeconds > 0
  property bool launchedThisCycle: false

  // Idle monitors are created on demand: a monitor whose `enabled` flips on
  // after creation never registers with the compositor (verified), so every
  // change of armed state / timeout tears the old one down and builds a new
  // one with `enabled: true` from the start. Launching is idempotent, so the
  // fallback firing while ours already runs costs one no-op CLI call.
  property var monitor: null
  property bool monitorIsTest: false
  readonly property bool monitorActive: !!monitor
  Component {
    id: monitorFactory
    IdleMonitor {
      property bool isTest: false
      enabled: true
      respectInhibitors: !isTest
      onIsIdleChanged: root.handleIdle(isIdle, isTest)
    }
  }
  function rebuildMonitor() {
    if (root.monitor) { root.monitor.destroy(); root.monitor = null }
    var test = root.testSeconds > 0
    if (!test && !root.armed) return
    root.monitor = monitorFactory.createObject(root, { timeout: test ? root.testSeconds : root.timeoutSeconds, isTest: test })
    root.monitorIsTest = test
    root.launchedThisCycle = false
  }
  onArmedChanged: rebuildMonitor()
  onTimeoutSecondsChanged: rebuildMonitor()
  onTestSecondsChanged: rebuildMonitor()

  function handleIdle(isIdle, isTest) {
    if (isIdle) {
      if (root.launchedThisCycle) return
      root.launchedThisCycle = true
      root.logEvent(isTest ? "idle test fired" : "idle fallback -> launch")
      root.launch(isTest)
      if (isTest) root.testSeconds = 0
    } else {
      root.launchedThisCycle = false
    }
  }

  property int launching: 0
  function launch(force) {
    var cmd = "[[ $(omarchy-shell lock isLocked 2>/dev/null) == \"true\" ]] || exec "
      + JSON.stringify(root.cli) + " launch --window-class " + root.screensaverClass + (force ? " --force" : "")
    var proc = shellRun.createObject(root, { args: ["bash", "-lc", cmd] })
    if (proc) { root.launching += 1; proc.running = true }
    return "ok"
  }

  Component {
    id: shellRun
    Process {
      property var args: []
      command: args
      stderr: StdioCollector {
        waitForEnd: true
        onStreamFinished: {
          var err = String(text || "").trim()
          if (err !== "") root.logEvent("launch: " + err)
        }
      }
      onExited: function(exitCode) {
        root.launching = Math.max(0, root.launching - 1)
        if (exitCode !== 0) root.logEvent("launch exited " + exitCode)
        destroy()
      }
    }
  }

  // Stock screensaver got there first (its idle timer won, e.g. because this
  // service was reloaded mid-idle and our monitor restarted from zero): the
  // launcher replaces it -- ours is spawned before theirs is torn down, so the
  // stock idle service keeps its lock timer. Launches are idempotent, so a
  // misjudged event costs one no-op CLI call.
  function handleHyprlandEvent(event) {
    if (String(event && event.name ? event.name : "") !== "openwindow") return
    var parts
    try { parts = event.parse(4) } catch (e) { parts = String(event && event.data ? event.data : "").split(",") }
    if (String(parts[2] || "") !== root.screensaverClass) return
    if (String(parts[3] || "") === root.ourTitle) return
    if (!root.armed || root.launching > 0) return
    root.launchedThisCycle = true
    root.logEvent("stock screensaver window " + parts[0] + " (" + parts[3] + ") -> replace")
    root.launch(false)
  }
  Connections {
    target: Hyprland
    function onRawEvent(event) { root.handleHyprlandEvent(event) }
  }

  // shell.json (Omarchy idle timings) -- a non-clone plugin is not handed
  // shellConfig, so read the file directly.
  FileView {
    id: shellJsonView
    path: root.shellJsonPath
    watchChanges: true
    printErrors: false
    onLoaded: root.parseShellJson()
    onFileChanged: reload()
  }
  function parseShellJson() {
    try {
      var j = JSON.parse(shellJsonView.text())
      root.shellIdle = j.idle || {}
    } catch (e) {
      root.shellIdle = {}
    }
  }

  // Our own state dir: the CLI touches `revision` after every mutation.
  FileView {
    id: configDirWatch
    path: root.configDir
    watchChanges: true
    printErrors: false
    onFileChanged: reloadDebounce.restart()
  }
  FileView {
    id: revisionWatch
    path: root.configDir + "/revision"
    watchChanges: true
    printErrors: false
    onFileChanged: reloadDebounce.restart()
  }
  FileView { path: root.togglesDir; watchChanges: true; printErrors: false; onFileChanged: flagsProbe.running = true }
  FileView { path: root.indicatorsDir; watchChanges: true; printErrors: false; onFileChanged: flagsProbe.running = true }
  Timer { interval: 15000; repeat: true; running: true; onTriggered: flagsProbe.running = true }

  Process {
    id: flagsProbe
    command: ["bash", "-c",
      "printf '{\"off\":%s,\"awake\":%s}' " +
      "$([[ -f \"$HOME/.local/state/omarchy/toggles/screensaver-off\" ]] && echo true || echo false) " +
      "$([[ -f \"$HOME/.local/state/omarchy/indicators/stay-awake\" ]] && echo true || echo false)"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var j = JSON.parse(String(text || "").trim())
          root.screensaverOff = !!j.off
          root.stayAwake = !!j.awake
          root.flagsLoaded = true
        } catch (e) {}
      }
    }
  }

  // ---- writes ------------------------------------------------------------
  Component {
    id: cliCall
    Process {
      property var args: []
      property bool reloadAfter: true
      property var onLine: null
      property var onDone: null
      property string collected: ""
      command: [root.cli].concat(args)
      environment: ({ PYTHONDONTWRITEBYTECODE: "1" })
      stdout: SplitParser {
        onRead: function(line) {
          if (onLine) onLine(line)
          else collected += line + "\n"
        }
      }
      stderr: StdioCollector {
        waitForEnd: true
        onStreamFinished: {
          var err = String(text || "").trim()
          if (err !== "") root.logEvent(args[0] + ": " + err.split("\n").pop())
        }
      }
      onExited: function(exitCode) {
        if (exitCode !== 0) root.lastError = "ansi-screensaver " + args.join(" ") + " failed (" + exitCode + ")"
        if (onDone) onDone(exitCode, collected)
        if (reloadAfter) Qt.callLater(root.reload)
        destroy()
      }
    }
  }

  function runCli(args, opts) {
    opts = opts || {}
    var proc = cliCall.createObject(root, {
      args: args,
      reloadAfter: opts.reloadAfter !== false,
      onLine: opts.onLine || null,
      onDone: opts.onDone || null
    })
    if (proc) proc.running = true
    return proc
  }

  // One long job at a time (add --all, thumbs, fetch, import of folders).
  property var job: null
  function startJob(name, args) {
    if (root.job) { root.logEvent("job busy: " + root.job.name); return "busy" }
    var state = { name: name, n: 0, total: 0, label: "", proc: null, error: "" }
    state.proc = root.runCli(args.concat(["--progress"]), {
      onLine: function(line) {
        var m = /^progress (\d+)\/(\d+) ?(.*)$/.exec(line)
        if (m) {
          root.job = Object.assign({}, root.job, { n: parseInt(m[1]), total: parseInt(m[2]), label: m[3] })
        } else if (line.indexOf("error ") === 0) {
          root.job = Object.assign({}, root.job, { error: line.substring(6) })
        }
      },
      onDone: function(exitCode, collected) {
        var j = root.job
        root.job = null
        root.logEvent("job " + name + " done rc=" + exitCode + (j && j.error ? " " + j.error : ""))
      }
    })
    root.job = state
    return "ok"
  }
  function cancelJob() {
    if (root.job && root.job.proc) root.job.proc.signal(15)
  }

  function setConfig(key, valueJson) {
    // optimistic update so controls don't snap back while the CLI runs
    try {
      var value = JSON.parse(valueJson)
      var cfg = JSON.parse(JSON.stringify(root.config))
      var parts = key.split(".")
      var cur = cfg
      for (var i = 0; i < parts.length - 1; i++) {
        if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {}
        cur = cur[parts[i]]
      }
      cur[parts[parts.length - 1]] = value
      root.snapshot = Object.assign({}, root.snapshot, { config: cfg })
    } catch (e) {}
    root.runCli(["config", "set", key, valueJson], {})
    root.logEvent("set " + key + "=" + valueJson)
    return "ok"
  }

  function libraryAction(action, id, opts) {
    root.runCli(["library", action, id], opts || {})
    root.logEvent(action + " " + id)
    return "ok"
  }

  // Omarchy's own idle timeouts (shell.json). Optimistic update; the CLI
  // writes through omarchy-shell-config and the shell.json watcher confirms.
  function setOmarchyIdle(key, seconds) {
    var n = parseInt(seconds)
    if (!isFinite(n) || n < 10) return "need seconds >= 10"
    if (key !== "screensaver" && key !== "lock") return "unknown key"
    var next = Object.assign({}, root.shellIdle); next[key] = n; root.shellIdle = next
    root.runCli(["idle", "set", "--" + key, String(n)], {})
    root.logEvent("omarchy idle." + key + "=" + n)
    return "ok"
  }

  function toggleTakeover() {
    var next = !root.takeoverEnabled
    root.setConfig("idle.takeover", next ? "true" : "false")
    return next ? "enabled" : "disabled"
  }

  function armTest(seconds) {
    var s = parseInt(seconds)
    if (!isFinite(s) || s < 3) return "need seconds >= 3"
    root.launchedThisCycle = false
    root.testSeconds = s
    root.logEvent("idle test armed " + s + "s")
    return "armed: launches after " + s + "s idle"
  }
  function disarmTest() { root.testSeconds = 0; return "ok" }

  function openGallery(payloadJson) {
    if (!root.shell || typeof root.shell.summon !== "function") return "no-shell"
    root.reload()
    return root.shell.summon(root.pluginId, payloadJson || "{}") ? "ok" : "failed"
  }

  function statusJson() {
    return JSON.stringify({
      armed: root.armed, takeoverEnabled: root.takeoverEnabled, screensaverOff: root.screensaverOff,
      stayAwake: root.stayAwake, flagsLoaded: root.flagsLoaded, screensaverSeconds: root.screensaverSeconds, lockSeconds: root.lockSeconds,
      fallbackSeconds: root.fallbackSeconds, timeoutSeconds: root.timeoutSeconds, idle: root.monitor ? root.monitor.isIdle : false,
      monitorActive: root.monitorActive, monitorTimeout: root.monitor ? root.monitor.timeout : null, monitorIsTest: root.monitorIsTest,
      launchedThisCycle: root.launchedThisCycle, testSeconds: root.testSeconds, launching: root.launching, stockWatch: true,
      library: root.library.length, loading: root.loading, error: root.lastError, lastEvent: root.lastEvent,
      job: root.job ? { name: root.job.name, n: root.job.n, total: root.job.total, label: root.job.label } : null
    })
  }

  Component.onCompleted: {
    root.reload()
    flagsProbe.running = true
    root.rebuildMonitor()
  }

  IpcHandler {
    target: "ansisaver"

    function open(): string { return root.openGallery("{}") }
    function openTab(tab: string): string { return root.openGallery(JSON.stringify({ tab: tab })) }
    // `qs ipc call` splits arguments on commas, so the path is "|"-joined:
    //   omarchy-shell ansisaver browse sixteencolors 'years|year/1996|pack/ice9607a'
    function browse(source: string, path: string): string {
      var segs = String(path || "").split("|").filter(function(s) { return s !== "" })
      return root.openGallery(JSON.stringify({ tab: "sources", source: source, path: segs }))
    }
    function launch(): string { return root.launch(true) }
    function stop(): string { root.runCli(["stop"], { reloadAfter: false }); return "ok" }
    function preview(id: string): string {
      root.runCli(id && id !== "" ? ["preview", id] : ["preview", "--random"], { reloadAfter: false }); return "ok"
    }
    function toggleTakeover(): string { return root.toggleTakeover() }
    function refresh(): string { root.reload(); return "ok" }
    function status(): string { return root.statusJson() }
    function armTest(seconds: string): string { return root.armTest(seconds) }
    function disarmTest(): string { return root.disarmTest() }
    function set(key: string, valueJson: string): string { return root.setConfig(key, valueJson) }
    function setIdle(key: string, seconds: string): string { return root.setOmarchyIdle(key, seconds) }
    function library(action: string, id: string): string { return root.libraryAction(action, id) }
  }
}
