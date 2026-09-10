import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Headless owner of the plugin state:
//  * the snapshot (library, config, doctor, sources) read from the CLI;
//  * idle takeover: our own IdleMonitor fires a little before Omarchy's, so
//    the stock launcher sees our window class and becomes a no-op while the
//    stock idle service keeps owning lock / wake / stay-awake;
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
  readonly property int leadSeconds: {
    var v = Number(root.config.idle ? root.config.idle.lead_seconds : 2)
    return isFinite(v) && v >= 1 ? Math.round(v) : 2
  }
  readonly property bool takeoverEnabled: !!(root.config.idle && root.config.idle.takeover)
  property bool screensaverOff: false
  property bool stayAwake: false
  property bool flagsLoaded: false
  property int testSeconds: 0
  readonly property int timeoutSeconds: Math.max(5, root.screensaverSeconds - root.leadSeconds)
  readonly property bool armed: root.flagsLoaded && root.takeoverEnabled && !root.screensaverOff
                                && !root.stayAwake && root.screensaverSeconds > 0
  property bool launchedThisCycle: false

  IdleMonitor {
    id: idleMonitor
    enabled: root.armed || root.testSeconds > 0
    timeout: root.testSeconds > 0 ? root.testSeconds : root.timeoutSeconds
    respectInhibitors: true
    onIsIdleChanged: root.handleIdle()
  }

  function handleIdle() {
    if (idleMonitor.isIdle) {
      if (root.launchedThisCycle) return
      root.launchedThisCycle = true
      var wasTest = root.testSeconds > 0
      root.testSeconds = 0
      root.logEvent(wasTest ? "idle test fired" : "idle -> launch")
      root.launch(false)
    } else {
      root.launchedThisCycle = false
    }
  }

  function launch(force) {
    var cmd = "[[ $(omarchy-shell lock isLocked 2>/dev/null) == \"true\" ]] || exec "
      + JSON.stringify(root.cli) + " launch --window-class " + root.screensaverClass + (force ? " --force" : "")
    var proc = shellRun.createObject(root, { args: ["bash", "-lc", cmd] })
    if (proc) proc.running = true
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
        if (exitCode !== 0) root.logEvent("launch exited " + exitCode)
        destroy()
      }
    }
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

  function libraryAction(action, id) {
    root.runCli(["library", action, id], {})
    root.logEvent(action + " " + id)
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
      stayAwake: root.stayAwake, flagsLoaded: root.flagsLoaded, screensaverSeconds: root.screensaverSeconds,
      leadSeconds: root.leadSeconds, timeoutSeconds: root.timeoutSeconds, idle: idleMonitor.isIdle,
      launchedThisCycle: root.launchedThisCycle, testSeconds: root.testSeconds,
      library: root.library.length, loading: root.loading, error: root.lastError, lastEvent: root.lastEvent,
      job: root.job ? { name: root.job.name, n: root.job.n, total: root.job.total, label: root.job.label } : null
    })
  }

  Component.onCompleted: {
    root.reload()
    flagsProbe.running = true
  }

  IpcHandler {
    target: "ansisaver"

    function open(): string { return root.openGallery("{}") }
    function openTab(tab: string): string { return root.openGallery(JSON.stringify({ tab: tab })) }
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
    function library(action: string, id: string): string { return root.libraryAction(action, id) }
  }
}
