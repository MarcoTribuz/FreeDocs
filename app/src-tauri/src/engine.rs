//! Spawns the Python engine and talks newline-delimited JSON to it.
//!
//! The engine is a child process, never a socket. It reads and writes files named
//! by whoever is on the other end of the pipe, so the only safe caller is a
//! parent process that already has the user's permission to touch those files.
//!
//! One process serves the whole session. Loading the NER model takes seconds and
//! running it takes milliseconds, so a design that spawned the engine per file
//! would spend its life loading a model.
//!
//! Locating the executable, in order:
//!   1. `FREEDOCS_ENGINE`, so a developer can point at anything
//!   2. the bundled `freedocs-engine` resource directory, which is what a release
//!      uses
//!   3. the repository's virtualenv, so `tauri dev` works without building a
//!      PyInstaller bundle first
//!
//! The third is why development is bearable; the second is why the app ships.
//!
//! The engine is also *told* where its data is, rather than looking for it. A
//! portable build carries the NER weights and the Tesseract language data beside
//! the executable, and `portable_env` names them on the child's environment. The
//! engine holds no rule about being portable and never works it out: it is handed
//! paths, and only ever paths that exist.

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};

/// Event the frontend listens on for anything the engine says unprompted:
/// progress, and the capabilities it announces at startup.
pub const NOTIFY_EVENT: &str = "engine://notify";

/// A request that never gets an answer would hang the UI for ever. The engine is
/// local and the slowest realistic call is OCR over a long scan, so this is
/// generous rather than tight.
///
/// It is also no longer what a *dead* engine costs. Until the reader thread
/// started reporting the end of the pipe, a request in flight when the sidecar
/// died sat here for the full ten minutes, and so did the window.
const REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(600);

/// The one request whose length is set by the network rather than the machine.
///
/// `model_fetch` downloads 1244 MB, so the ten minutes above run out below about
/// 2 MB/s - and a timeout here does not stop the download, it only makes the
/// window report a failure while the engine carries on fetching. The hub client
/// has its own read timeouts, so a stalled connection still ends as an error
/// from the engine; this is only the ceiling for a slow one that keeps moving.
const DOWNLOAD_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(6 * 60 * 60);

fn timeout_for(method: &str) -> std::time::Duration {
    if method == "model_fetch" {
        DOWNLOAD_TIMEOUT
    } else {
        REQUEST_TIMEOUT
    }
}

/// How many times one session will start the engine again after it has died.
///
/// Bounded rather than unlimited, because the realistic cause is a document the
/// parser cannot survive, and retrying it is a crash loop that pays for a
/// GLiNER2 load every time round. Three is enough for "that one file killed it,
/// carry on with the rest" and short of "every request restarts the process".
const MAX_RESTARTS: u64 = 3;

/// The half of the engine that can be replaced. Absent between the sidecar dying
/// and the next request starting a new one.
struct Live {
    stdin: ChildStdin,
    child: Child,
}

/// Where the engine is and what it is told, resolved once.
///
/// Once rather than per restart, deliberately: a session that started against
/// one engine must not silently continue against a different one because a
/// bundle changed under it. It also leaves nothing Tauri-shaped in the restart
/// path, which is what makes the part below testable against a fake sidecar.
struct Launch {
    executable: PathBuf,
    env: Vec<(&'static str, OsString)>,
    identity: Identity,
}

/// Which of `locate`'s three routes named the executable.
///
/// Recorded where the choice is made and never re-derived. "Where is the engine"
/// answered twice is two answers that can disagree, and the window would be the
/// one guessing - from the shape of a path, which is the mistake it already made
/// once reading a colon in a detector string as "the model".
///
/// A closed vocabulary on the wire, so the window translates it by key. Same
/// treatment as the engine's stage names, and pinned by a test for the same
/// reason.
#[derive(Clone, Copy, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    Override,
    Bundled,
    Checkout,
}

/// The engine that is running, as the process that started it sees it.
///
/// This half cannot come from Python. In a checkout the app spawns
/// `freedocs-rpc` while the engine's own `sys.executable` is the interpreter, so
/// an engine-side build date would be the modification time of Python. The
/// launcher owns the identity of the thing it launched.
///
/// It exists because a stale sidecar was indistinguishable from a machine with no
/// Tesseract: a 23 August bundle and a 24 August one both call themselves 0.1.0,
/// so the version cannot tell them apart and the route and the date are the only
/// facts that can.
///
/// Nothing here decides that a build is *stale*. Neither half knows what the
/// current build is, and comparing this against the app binary's own timestamp
/// was considered and rejected - `tauri build` does not promise to preserve
/// resource timestamps, and in a checkout the two diverge by design, so the
/// comparison would be a verdict resting on an accident.
#[derive(Clone, serde::Serialize)]
pub struct Identity {
    executable: String,
    source: Source,
    /// Seconds since the epoch, or null. **Null rather than zero**: a zero
    /// renders as 1 January 1970, which is a wrong date and not an absent one.
    modified: Option<u64>,
}

fn identify(path: &Path, source: Source) -> Identity {
    let modified = std::fs::metadata(path)
        .and_then(|data| data.modified())
        .ok()
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|since| since.as_secs());
    Identity {
        executable: path.to_string_lossy().into_owned(),
        source,
        modified,
    }
}

/// A request waiting for its answer, and which process it was written to.
///
/// The process is recorded because "the engine died" is a fact about one
/// generation. `on_disconnect` used to fail every waiting request, and it runs
/// after the slot is already empty - so a request that arrived in that moment
/// found no engine, started the next one, and was then failed with the old
/// one's exit status. The macOS release build of 1.3.0 hit exactly that, in
/// `the_next_request_starts_the_engine_again`.
///
/// An atomic rather than a field under `pending`'s lock, because `send` records
/// it while holding `live`, and the two locks are never held together.
struct Waiting {
    sender: Sender<Value>,
    /// The generation this request was written to; 0 until it has been.
    sent_to: Arc<AtomicU64>,
}

pub struct Engine {
    launch: Launch,
    /// Where a notification goes. A closure rather than an `AppHandle` so this
    /// type knows nothing about Tauri - the same reason `lib.rs` is thin.
    notify: Box<dyn Fn(Value) + Send + Sync>,
    live: Mutex<Option<Live>>,
    pending: Mutex<HashMap<u64, Waiting>>,
    next_id: AtomicU64,
    /// Which start the live process is. A reader thread outlives its own
    /// process by a moment, so it carries the number it was started with and
    /// compares: "my process ended" and "a process ended, and a newer one is
    /// already running" need opposite handling.
    generation: AtomicU64,
    restarts: AtomicU64,
}

impl Engine {
    pub fn spawn(app: &AppHandle) -> Result<Arc<Self>, String> {
        let (executable, source) = locate(app)?;
        // Read once, at startup, with the rest of `Launch`: a session that began
        // against one engine must not later report a different one.
        let identity = identify(&executable, source);
        let launch = Launch {
            executable,
            env: portable_env(resource_root(app).as_deref()),
            identity,
        };
        let handle = app.clone();
        Engine::start(
            launch,
            Box::new(move |message| {
                let _ = handle.emit(NOTIFY_EVENT, message);
            }),
        )
    }

    /// Which engine this session is talking to.
    ///
    /// Resolved once with the rest of `Launch`, so it describes the process that
    /// is actually serving requests rather than whatever is on disk now.
    pub fn identity(&self) -> Identity {
        self.launch.identity.clone()
    }

    fn start(
        launch: Launch,
        notify: Box<dyn Fn(Value) + Send + Sync>,
    ) -> Result<Arc<Self>, String> {
        let engine = Arc::new(Engine {
            launch,
            notify,
            live: Mutex::new(None),
            pending: Mutex::new(HashMap::new()),
            next_id: AtomicU64::new(1),
            generation: AtomicU64::new(0),
            restarts: AtomicU64::new(0),
        });
        // The first start is the one allowed to fail the whole thing: no engine
        // at startup means no engine found, which the window explains. A later
        // failure is a restart, and is reported against the request that asked.
        {
            let mut live = engine
                .live
                .lock()
                .map_err(|_| "the engine lock is poisoned".to_string())?;
            engine.start_process(&mut live)?;
        }
        Ok(engine)
    }

    /// Start the sidecar and the thread that reads it, **into the caller's
    /// slot**, which the caller is holding the lock on.
    ///
    /// The slot rather than a return value, because the order is load-bearing
    /// and returning one gets it wrong. Spawning the reader before the process
    /// is installed leaves a window in which the sidecar can die, the reader can
    /// report it against an empty slot, and the dead process is then written
    /// into that slot by the code that started it. The next request writes into
    /// its pipe, the write succeeds into a buffer nobody will read, no reader
    /// remains to notice the end of it, and the call waits out the whole
    /// ten-minute timeout - the exact failure this commit is about, reintroduced
    /// by the fix for it. A fake sidecar that exits on its first line is what
    /// found it.
    ///
    /// Holding the lock across the spawn is safe: the reader's `on_disconnect`
    /// wants the same lock and simply waits for the caller to finish.
    fn start_process(self: &Arc<Self>, slot: &mut Option<Live>) -> Result<(), String> {
        let executable = &self.launch.executable;
        let mut command = Command::new(executable);
        for (name, value) in &self.launch.env {
            command.env(name, value);
        }
        hide_console(&mut command);
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            // stderr is left inherited on purpose: a Python traceback should
            // reach the terminal a developer is watching rather than vanish.
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| format!("could not start the engine at {executable:?}: {error}"))?;

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "the engine was started without a stdout pipe".to_string())?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "the engine was started without a stdin pipe".to_string())?;

        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        *slot = Some(Live { stdin, child });

        let engine = Arc::clone(self);
        std::thread::spawn(move || {
            read_loop(&engine, BufReader::new(stdout));
            // The loop ends only at end of pipe, which is the sidecar being gone.
            engine.on_disconnect(generation);
        });
        Ok(())
    }

    /// Everything that happens when the engine stops answering.
    ///
    /// Three things, and the middle one is why this exists at all.
    ///
    /// The child is **reaped**: an unwaited child is a zombie for the life of
    /// the app, and its exit status is the only account of *how* the engine
    /// died - a signal reads very differently from a clean exit.
    ///
    /// Every request still waiting on *this* process is **failed now**. Their
    /// senders used to sit
    /// in the map untouched, so a request in flight when the sidecar died waited
    /// out the full ten-minute timeout with the window waiting with it. The
    /// window is told this way rather than by a new notification: an event
    /// nobody consumes is dead protocol, and a fault that heals before the next
    /// request is a fault worth not mentioning. Only this process's requests:
    /// one not yet written will start, or reach, the next process - see
    /// [`Waiting`].
    ///
    /// And the slot is **emptied**, which is what lets the next request start a
    /// new one.
    fn on_disconnect(&self, generation: u64) {
        if self.generation.load(Ordering::SeqCst) != generation {
            return;
        }
        let status = {
            let taken = self.live.lock().ok().and_then(|mut live| live.take());
            match taken {
                Some(Live { stdin, mut child }) => {
                    // The end of stdout is not the end of the process. `wait`
                    // with our end of stdin still open leaves an engine that is
                    // alive but no longer read blocked on a read for ever, and
                    // this thread blocked on it - so close the pipe, and stop an
                    // engine that has not already exited by itself.
                    drop(stdin);
                    if let Ok(None) = child.try_wait() {
                        let _ = child.kill();
                    }
                    child.wait().ok()
                }
                None => None,
            }
        };
        let detail = describe_exit(status);

        let waiting: Vec<Sender<Value>> = match self.pending.lock() {
            Ok(mut pending) => {
                let ours: Vec<u64> = pending
                    .iter()
                    .filter(|(_, waiting)| waiting.sent_to.load(Ordering::SeqCst) == generation)
                    .map(|(id, _)| *id)
                    .collect();
                ours.into_iter()
                    .filter_map(|id| pending.remove(&id))
                    .map(|waiting| waiting.sender)
                    .collect()
            }
            Err(_) => Vec::new(),
        };
        for sender in waiting {
            let _ = sender.send(disconnected(&detail));
        }
    }

    /// Send one request and wait for the response with the matching id.
    ///
    /// Blocking, and therefore only ever called from a blocking task: a scrub
    /// with OCR takes seconds and the window must stay alive throughout.
    pub fn request(self: &Arc<Self>, method: &str, params: Value) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver): (Sender<Value>, Receiver<Value>) = channel();
        let sent_to = Arc::new(AtomicU64::new(0));
        self.pending
            .lock()
            .map_err(|_| "the engine lock is poisoned".to_string())?
            .insert(
                id,
                Waiting {
                    sender,
                    sent_to: Arc::clone(&sent_to),
                },
            );

        let request = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        if let Err(error) = self.send(&request, &sent_to) {
            // Removed rather than left to time out, for the same reason
            // `on_disconnect` drains the map: nothing else will ever answer it.
            if let Ok(mut pending) = self.pending.lock() {
                pending.remove(&id);
            }
            return Err(error);
        }

        let timeout = timeout_for(method);
        let response = receiver
            .recv_timeout(timeout)
            .map_err(|_| format!("the engine did not answer {method:?} within {timeout:?}"))?;

        if let Some(error) = response.get("error") {
            // Returned as an error string carrying the engine's own structured
            // payload: the app renders "install OCR" differently from "this is a
            // bug", and it can only tell them apart by the code.
            return Err(error.to_string());
        }
        Ok(response.get("result").cloned().unwrap_or(Value::Null))
    }

    /// Write one line, starting the engine again first if it is not there.
    ///
    /// Restarted lazily, on the request that needs it, rather than the moment
    /// the old one died: a session that is finished with the engine should not
    /// pay for a model reload it will never use. The whole check-and-start
    /// happens under one lock, so two requests racing after a crash produce one
    /// process rather than two.
    fn send(self: &Arc<Self>, request: &Value, sent_to: &AtomicU64) -> Result<(), String> {
        let mut live = self
            .live
            .lock()
            .map_err(|_| "the engine lock is poisoned".to_string())?;
        if live.is_none() {
            if self.restarts.fetch_add(1, Ordering::SeqCst) >= MAX_RESTARTS {
                return Err(format!(
                    "the engine has stopped {MAX_RESTARTS} times in this session and \
                     will not be started again; restart the application"
                ));
            }
            self.start_process(&mut live)?;
        }
        let process = live
            .as_mut()
            .ok_or_else(|| "the engine is not running".to_string())?;
        // Under `live`, so this is the generation of the process in the slot.
        sent_to.store(self.generation.load(Ordering::SeqCst), Ordering::SeqCst);
        writeln!(process.stdin, "{request}")
            .map_err(|error| format!("engine write failed: {error}"))?;
        process
            .stdin
            .flush()
            .map_err(|error| format!("engine flush failed: {error}"))
    }
}

/// The response a request gets when the sidecar died under it.
///
/// Shaped like the engine's own error so `request` needs no second path, and
/// carrying a code outside the engine's range: this did not come from the engine
/// and must not be mistaken for something it said.
fn disconnected(detail: &str) -> Value {
    json!({
        "jsonrpc": "2.0",
        "error": {
            "code": -32000,
            "message": format!(
                "the engine stopped before answering ({detail}); \
                 the next request will start it again"
            ),
        }
    })
}

/// How the engine died, in a sentence, for the message a caller sees.
///
/// A signal and a clean exit read very differently - one is a crash inside a
/// parser, the other is the engine deciding to stop - and "it stopped" alone
/// tells nobody which.
fn describe_exit(status: Option<std::process::ExitStatus>) -> String {
    let Some(status) = status else {
        return "no exit status".to_string();
    };
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        if let Some(signal) = status.signal() {
            return format!("killed by signal {signal}");
        }
    }
    match status.code() {
        Some(0) => "exited normally".to_string(),
        Some(code) => format!("exit status {code}"),
        None => "no exit status".to_string(),
    }
}

fn read_loop(engine: &Arc<Engine>, mut reader: BufReader<std::process::ChildStdout>) {
    // Bytes, then a lossy decode, rather than `lines()`. `lines()` ends with an
    // error on the first line that is not valid UTF-8, and ending the loop is
    // what declares the engine dead - so one stray byte from a C library on fd 1
    // took the whole session down, which is what a cp1252 engine did to every
    // response carrying an accent.
    let mut buffer = Vec::new();
    loop {
        buffer.clear();
        match reader.read_until(b'\n', &mut buffer) {
            Ok(0) | Err(_) => break,
            Ok(_) => {}
        }
        let line = String::from_utf8_lossy(&buffer);
        if line.trim().is_empty() {
            continue;
        }
        let Ok(message) = serde_json::from_str::<Value>(&line) else {
            // The length, never the line: on this pipe a line is as likely to
            // be part of a document as anything else, and stderr reaches the
            // system log.
            eprintln!("engine sent a line that is not JSON ({} bytes)", buffer.len());
            continue;
        };

        match message.get("id").and_then(Value::as_u64) {
            Some(id) => {
                let sender = engine
                    .pending
                    .lock()
                    .ok()
                    .and_then(|mut pending| pending.remove(&id))
                    .map(|waiting| waiting.sender);
                if let Some(sender) = sender {
                    let _ = sender.send(message);
                }
            }
            // No id: a notification. Progress and the startup announcement both
            // arrive this way, and both are for the window rather than for a
            // waiting caller.
            None => {
                (engine.notify)(message);
            }
        }
    }
}

/// Where this build's resources are, whatever shape it was packaged in.
///
/// One resolution, shared by `locate` and `portable_env`, because "where are my
/// resources" answered twice is two answers that can disagree — and Tauri already
/// knows all three shapes: `Contents/Resources` inside a macOS `.app`, `usr/lib/
/// <product>` inside a mounted AppImage, and the executable's own directory when
/// nothing was bundled, which is exactly the portable zip's layout.
fn resource_root(app: &AppHandle) -> Option<PathBuf> {
    app.path().resource_dir().ok()
}

/// Environment for the sidecar, derived from what is actually beside the app.
///
/// Only paths that exist are passed, and an already-set variable is never
/// overwritten — the same precedence `FREEDOCS_ENGINE` has above. A variable
/// naming a directory that is not there would be worse than no variable at all:
/// the engine reads `FREEDOCS_TESSDATA` as an explicit choice, and
/// `FREEDOCS_NER_MODEL` refuses a path it cannot load rather than quietly
/// downloading 1.2 GB instead.
///
/// So a macOS or Linux installer build, where none of these exist, hands the
/// engine an unchanged environment. A Windows installer gains exactly one
/// variable, `FREEDOCS_TESSERACT`, pointing at the Tesseract it carries in `bin/`;
/// its model and language data still come the installer's way.
fn portable_env(root: Option<&Path>) -> Vec<(&'static str, OsString)> {
    let mut env = Vec::new();
    let Some(root) = root else {
        return env;
    };

    let model = root.join("ner-model");
    let bundled_model = model.join("config.json").is_file();
    if bundled_model {
        set(&mut env, "FREEDOCS_NER_MODEL", model.into_os_string());
        // Only alongside a bundled model, and this is the half that makes
        // "offline" true rather than merely likely. Without it, an air-gapped
        // machine can still spend a DNS timeout inside `from_pretrained` before
        // reading weights it already has.
        set(&mut env, "HF_HUB_OFFLINE", OsString::from("1"));
        set(&mut env, "TRANSFORMERS_OFFLINE", OsString::from("1"));
    }

    let tessdata = root.join("tessdata");
    if has_traineddata(&tessdata) {
        set(&mut env, "FREEDOCS_TESSDATA", tessdata.into_os_string());
    }

    // The Windows installers ship one here: `tauri.windows.conf.json` maps the
    // UB Mannheim build staged by `packaging/tesseract_windows.py` to `bin/`,
    // a self-contained directory whose DLLs Windows resolves beside the
    // executable. macOS and Linux do not - there Tesseract is a platform package
    // linked against system libraries - so on those this stays the hook that
    // lets a user drop one in without a rebuild. Either way the engine validates
    // it before believing it.
    let binary = root
        .join("bin")
        .join(if cfg!(windows) { "tesseract.exe" } else { "tesseract" });
    if binary.is_file() {
        set(&mut env, "FREEDOCS_TESSERACT", binary.into_os_string());
    }

    env
}

/// Push unless the user already said otherwise.
fn set(env: &mut Vec<(&'static str, OsString)>, name: &'static str, value: OsString) {
    if std::env::var_os(name).is_none() {
        env.push((name, value));
    }
}

fn has_traineddata(directory: &Path) -> bool {
    let Ok(entries) = std::fs::read_dir(directory) else {
        return false;
    };
    entries.flatten().any(|entry| {
        entry
            .path()
            .extension()
            .is_some_and(|extension| extension == "traineddata")
    })
}

fn locate(app: &AppHandle) -> Result<(PathBuf, Source), String> {
    if let Ok(override_path) = std::env::var("FREEDOCS_ENGINE") {
        let path = PathBuf::from(override_path);
        if path.is_file() {
            return Ok((path, Source::Override));
        }
        return Err(format!("FREEDOCS_ENGINE points at {path:?}, which is not a file"));
    }

    let executable = if cfg!(windows) {
        "freedocs-engine.exe"
    } else {
        "freedocs-engine"
    };
    if let Some(resources) = resource_root(app) {
        let bundled = resources.join("freedocs-engine").join(executable);
        if bundled.is_file() {
            return Ok((bundled, Source::Bundled));
        }
    }

    for candidate in dev_candidates() {
        if candidate.is_file() {
            return Ok((candidate, Source::Checkout));
        }
    }

    Err("no engine found: build the sidecar with engine/packaging/build.py, or set \
         FREEDOCS_ENGINE"
        .to_string())
}

/// The repository virtualenv, relative to the compiled binary. Only ever hit
/// during development, where the binary sits in `app/src-tauri/target/<profile>/`.
fn dev_candidates() -> Vec<PathBuf> {
    let Ok(current) = std::env::current_exe() else {
        return Vec::new();
    };
    let mut roots = Vec::new();
    for ancestor in current.ancestors().skip(1).take(6) {
        roots.push(ancestor.to_path_buf());
    }

    let relative = if cfg!(windows) {
        ["engine", ".venv", "Scripts", "freedocs-rpc.exe"]
    } else {
        ["engine", ".venv", "bin", "freedocs-rpc"]
    };

    roots
        .into_iter()
        .map(|root| relative.iter().fold(root, |path, part| path.join(part)))
        .collect()
}

/// Keep the sidecar's console off the screen on Windows.
///
/// The sidecar is a console program (`console=True` in the PyInstaller spec)
/// started by a GUI one, and Windows answers that by opening a new console
/// window for it: a black `cmd` box that sits beside the app for the whole
/// session, says nothing about what it is, and kills the engine if closed. A
/// first-time user reads that as malware or a crash and closes everything.
///
/// `CREATE_NO_WINDOW` rather than building the sidecar windowed: the process
/// still gets a console, just an invisible one, so its stdio pipes behave as
/// they always have and Tesseract - which PyMuPDF spawns as a console child of
/// the engine - inherits the hidden console instead of flashing a window of
/// its own on every scanned page. A windowed (`console=False`) build would get
/// neither. Nothing here has been run on Windows yet.
#[cfg(windows)]
fn hide_console(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_command: &mut Command) {}

#[cfg(all(test, unix))]
mod lifecycle {
    //! What happens when the sidecar dies, against a fake one that dies on cue.
    //!
    //! Testable at all because `Engine` no longer knows about Tauri: it is given
    //! a path, an environment and somewhere to send notifications, so a shell
    //! script speaking two lines of JSON-RPC stands in for the engine.
    //!
    //! **Unix only, and that is a gap rather than a decision.** The fake is a
    //! bash script; a Windows equivalent would be a second fixture in a
    //! second language, testing the same Rust. The behaviour under test has no
    //! platform-specific code in it - the one `cfg` is `describe_exit`'s signal
    //! branch, which is covered below - so this is the usual shape for this
    //! project: verified on one platform, said out loud rather than implied.

    use super::{describe_exit, Engine, Launch, Waiting};
    use serde_json::json;
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::mpsc::channel;
    use std::sync::Arc;

    /// A sidecar in three lines of shell: read a request, answer it, or stop.
    ///
    /// `body` runs in a loop over stdin with `$line` holding one request, so a
    /// test writes only the interesting part.
    ///
    /// The first line closes every descriptor above stderr, and the tests hang
    /// without it. On macOS the standard library makes a pipe with `pipe()` and
    /// marks it close-on-exec in a second call; a sibling test spawning in
    /// between hands its child the other engine's pipe, and that child lives as
    /// long as the test binary. So a fake that died kept a writer on its stdout
    /// somewhere else, its reader never saw the end of the pipe, and the request
    /// waited out the ten-minute timeout: six runs in a hundred and fifty, with
    /// `lsof` showing an `answers` fake holding three pipes that were not its
    /// own. A shipped app starts one engine at a time, so this stays in the tests.
    /// Bash rather than `/bin/sh`: on Ubuntu that is dash, which reads `exec 10>&-`
    /// as a command named `10` - the first Linux run of this fix failed on it.
    fn fake(directory: &std::path::Path, name: &str, body: &str) -> PathBuf {
        let path = directory.join(name);
        let mut file = std::fs::File::create(&path).unwrap();
        write!(file, "#!/bin/bash
fd=3; while [ $fd -lt 64 ]; do eval \"exec $fd>&-\"; fd=$((fd + 1)); done
while IFS= read -r line; do
{body}
done
").unwrap();
        drop(file);
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
        path
    }

    /// Retries `Text file busy`, which is these fixtures and not the engine.
    ///
    /// The tests run in parallel and each writes a script and then executes it.
    /// A sibling that forks while this one's script is still open for writing
    /// hands its child that descriptor until the child reaches `exec`, and Linux
    /// refuses to execute a file somebody holds open for writing (ETXTBSY). The
    /// first Linux CI run failed on exactly that. A shipped sidecar is never
    /// written by the process that starts it, so this stays in the tests.
    fn engine(executable: PathBuf) -> Arc<Engine> {
        let mut attempts = 0;
        loop {
            let identity = super::identify(&executable, super::Source::Checkout);
            let started = Engine::start(
                Launch {
                    executable: executable.clone(),
                    env: Vec::new(),
                    identity,
                },
                Box::new(|_| {}),
            );
            match started {
                Err(error) if error.contains("os error 26") && attempts < 50 => {
                    attempts += 1;
                    std::thread::sleep(std::time::Duration::from_millis(20));
                }
                other => return other.unwrap(),
            }
        }
    }

    /// Echoes back an empty result for whatever id it was sent.
    ///
    /// `[0-9][0-9]*` rather than `[0-9]*`: the leading `.*` is greedy and eats
    /// the digits, so a capture that accepts zero of them matches happily and
    /// yields `"id":`, which is not JSON. The engine logged that and carried on,
    /// so the request was simply never answered - a broken fixture wearing the
    /// costume of the bug under test. Hence the `case`: a fake that cannot find
    /// an id stops, rather than emitting something almost right.
    const ANSWERS: &str = r#"  id=$(printf '%s' "$line" | sed 's/.*"id":\([0-9][0-9]*\).*/\1/')
  case "$id" in ''|*[!0-9]*) exit 1 ;; esac
  printf '{"jsonrpc":"2.0","id":%s,"result":{"ok":true}}\n' "$id""#;

    /// Block until the reader has noticed the sidecar is gone.
    ///
    /// The transition is asynchronous by design - a request must not wait on
    /// another process's death - so a test that wants to observe the state
    /// *after* it has to say so rather than assume.
    fn wait_until_stopped(engine: &Arc<Engine>) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while std::time::Instant::now() < deadline {
            if engine.live.lock().map(|live| live.is_none()).unwrap_or(false) {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        panic!("the engine never reported that it had stopped");
    }

    #[test]
    fn a_request_is_answered_by_the_engine_that_is_running() {
        let dir = tempfile::tempdir().unwrap();
        let engine = engine(fake(dir.path(), "answers", ANSWERS));
        assert_eq!(
            engine.request("capabilities", json!({})).unwrap(),
            json!({"ok": true})
        );
    }

    #[test]
    fn a_request_in_flight_when_the_engine_dies_fails_at_once() {
        // The whole point of the reader reporting end-of-pipe. Before it did,
        // the sender sat in `pending` untouched and this call waited out the
        // ten-minute timeout with the window waiting with it - so the assertion
        // that matters here is the clock as much as the message.
        let dir = tempfile::tempdir().unwrap();
        let engine = engine(fake(dir.path(), "dies", "  exit 3"));

        let started = std::time::Instant::now();
        let error = engine.request("inspect", json!({})).unwrap_err();
        assert!(
            started.elapsed() < std::time::Duration::from_secs(10),
            "it waited {:?}, which is the timeout doing the work",
            started.elapsed()
        );
        assert!(error.contains("stopped before answering"), "{error}");
        assert!(error.contains("exit status 3"), "{error}");
    }

    #[test]
    fn the_next_request_starts_the_engine_again() {
        // A fake that answers once and then leaves. The second call has no
        // process to write to, so it is the restart or it is nothing.
        let dir = tempfile::tempdir().unwrap();
        let body = format!("{ANSWERS}
  exit 0");
        let engine = engine(fake(dir.path(), "once", &body));

        assert!(engine.request("capabilities", json!({})).is_ok());
        wait_until_stopped(&engine);
        // Nothing is listening now, so this answer can only have come from a
        // process that did not exist a moment ago.
        assert_eq!(
            engine.request("capabilities", json!({})).unwrap(),
            json!({"ok": true})
        );
    }

    #[test]
    fn a_dead_engine_fails_only_the_requests_written_to_it() {
        // Deterministic form of the race the macOS release build lost: the
        // slot is empty before `on_disconnect` drains, so a request can arrive,
        // start the next process and be waiting by the time the drain runs.
        let dir = tempfile::tempdir().unwrap();
        let engine = engine(fake(dir.path(), "once-more", &format!("{ANSWERS}\n  exit 0")));
        assert!(engine.request("capabilities", json!({})).is_ok());
        wait_until_stopped(&engine);
        let dead = engine.generation.load(Ordering::SeqCst);

        let waiting = |sent_to: u64| {
            let (sender, receiver) = channel();
            let waiting = Waiting {
                sender,
                sent_to: Arc::new(AtomicU64::new(sent_to)),
            };
            (waiting, receiver)
        };
        let (written, written_rx) = waiting(dead);
        let (unwritten, unwritten_rx) = waiting(0);
        engine.pending.lock().unwrap().insert(9001, written);
        engine.pending.lock().unwrap().insert(9002, unwritten);

        engine.on_disconnect(dead);

        assert!(written_rx.try_recv().is_ok(), "the dead process's request waits on");
        assert!(
            unwritten_rx.try_recv().is_err(),
            "a request not yet written was failed with another process's exit"
        );
        assert!(engine.pending.lock().unwrap().contains_key(&9002));
    }

    #[test]
    fn an_engine_that_keeps_dying_is_eventually_left_alone() {
        // A crash loop pays for a GLiNER2 load every time round, and the
        // realistic cause is a document the parser cannot survive - which
        // retrying does not fix.
        let dir = tempfile::tempdir().unwrap();
        let engine = engine(fake(dir.path(), "always-dies", "  exit 1"));

        // Each round waits for the slot to empty before asking again. Without
        // that the loop is a race rather than a count: losing the process is
        // asynchronous, so a request sent before the reader has noticed writes
        // into a dead pipe, fails, and spends none of the budget - which is
        // correct behaviour and a useless way to test the budget.
        let mut refusal = None;
        for _ in 0..(super::MAX_RESTARTS + 2) {
            let error = engine.request("inspect", json!({})).unwrap_err();
            if error.contains("will not be started again") {
                refusal = Some(error);
                break;
            }
            wait_until_stopped(&engine);
        }
        let refusal = refusal.expect("the restart budget must run out");
        assert!(refusal.contains("restart the application"), "{refusal}");
    }

    #[test]
    fn a_line_that_is_not_utf8_does_not_end_the_session() {
        // `\351` is `é` in cp1252 and not valid UTF-8 - what a Windows engine
        // reading its locale's encoding wrote for every accented path. `lines()`
        // ended the reader on it, which declared a live engine dead.
        let dir = tempfile::tempdir().unwrap();
        let body = format!("  printf 'activit\\351\\n'
{ANSWERS}");
        let engine = engine(fake(dir.path(), "stray-byte", &body));
        assert_eq!(
            engine.request("capabilities", json!({})).unwrap(),
            json!({"ok": true})
        );
        assert_eq!(
            engine.request("capabilities", json!({})).unwrap(),
            json!({"ok": true})
        );
    }

    #[test]
    fn an_engine_that_closes_stdout_but_stays_alive_is_stopped() {
        // End of stdout is not the end of the process. Waiting on one that is
        // still running, with our end of its stdin open, never returned - and
        // the request in flight waited out the whole timeout behind it.
        let dir = tempfile::tempdir().unwrap();
        let engine = engine(fake(dir.path(), "mute", "  exec 1>&-\n  sleep 60"));

        let started = std::time::Instant::now();
        let error = engine.request("inspect", json!({})).unwrap_err();
        assert!(
            started.elapsed() < std::time::Duration::from_secs(10),
            "it waited {:?}",
            started.elapsed()
        );
        assert!(error.contains("stopped before answering"), "{error}");
    }

    #[test]
    fn a_signal_and_a_clean_exit_do_not_read_the_same() {
        // "It stopped" tells nobody whether a parser took the process down or
        // the engine decided to stop, and those are different problems.
        use std::os::unix::process::ExitStatusExt;
        assert_eq!(
            describe_exit(Some(std::process::ExitStatus::from_raw(9))),
            "killed by signal 9"
        );
        assert_eq!(describe_exit(None), "no exit status");
    }
}

#[cfg(test)]
mod tests {
    //! `portable_env` only, because it is the only new thing here with a
    //! decision in it. Everything around it needs a running `AppHandle`, and a
    //! test that builds one tests Tauri.

    use super::{has_traineddata, identify, portable_env, Source};
    use std::fs;
    use std::path::Path;
    use std::sync::{Mutex, MutexGuard};

    /// `portable_env` consults the process environment, and one test below sets a
    /// variable in it. Cargo runs tests in threads of one process, so without
    /// this that write is visible to whichever sibling happens to be running —
    /// a test that passes until the machine is busy.
    static ENV: Mutex<()> = Mutex::new(());

    fn serialised() -> MutexGuard<'static, ()> {
        ENV.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn value<'a>(env: &'a [(&str, std::ffi::OsString)], name: &str) -> Option<&'a std::ffi::OsStr> {
        env.iter()
            .find(|(key, _)| *key == name)
            .map(|(_, value)| value.as_os_str())
    }

    fn model_at(root: &Path) -> std::path::PathBuf {
        let model = root.join("ner-model");
        fs::create_dir_all(&model).unwrap();
        fs::write(model.join("config.json"), "{}").unwrap();
        model
    }

    #[test]
    fn no_root_means_no_variables() {
        let _guard = serialised();
        assert!(portable_env(None).is_empty());
    }

    #[test]
    fn an_installer_layout_hands_over_an_unchanged_environment() {
        let _guard = serialised();
        // The additive claim, asserted rather than assumed: a build with none of
        // these resources must behave exactly as it did before any of this
        // existed.
        let root = tempfile::tempdir().unwrap();
        assert!(portable_env(Some(root.path())).is_empty());
    }

    #[test]
    fn a_bundled_model_is_named_and_turns_the_network_off() {
        let _guard = serialised();
        let root = tempfile::tempdir().unwrap();
        let model = model_at(root.path());
        let env = portable_env(Some(root.path()));
        assert_eq!(value(&env, "FREEDOCS_NER_MODEL"), Some(model.as_os_str()));
        // Offline is set only alongside a bundled model, because it is the thing
        // that makes "offline" true rather than merely likely.
        assert_eq!(value(&env, "HF_HUB_OFFLINE").unwrap(), "1");
        assert_eq!(value(&env, "TRANSFORMERS_OFFLINE").unwrap(), "1");
    }

    #[test]
    fn a_directory_without_a_config_is_not_a_model() {
        let _guard = serialised();
        // Passing it anyway would be worse than passing nothing: the engine
        // refuses a path it cannot load rather than falling back to the hub, so
        // this would break a build that would otherwise have worked.
        let root = tempfile::tempdir().unwrap();
        fs::create_dir_all(root.path().join("ner-model")).unwrap();
        let env = portable_env(Some(root.path()));
        assert!(value(&env, "FREEDOCS_NER_MODEL").is_none());
        assert!(value(&env, "HF_HUB_OFFLINE").is_none());
    }

    #[test]
    fn tessdata_counts_only_when_it_holds_language_data() {
        let _guard = serialised();
        let root = tempfile::tempdir().unwrap();
        let tessdata = root.path().join("tessdata");
        fs::create_dir_all(&tessdata).unwrap();
        assert!(!has_traineddata(&tessdata));
        assert!(value(&portable_env(Some(root.path())), "FREEDOCS_TESSDATA").is_none());

        fs::write(tessdata.join("ita.traineddata"), "x").unwrap();
        assert!(has_traineddata(&tessdata));
        let env = portable_env(Some(root.path()));
        assert_eq!(value(&env, "FREEDOCS_TESSDATA"), Some(tessdata.as_os_str()));
    }

    #[test]
    fn a_tesseract_dropped_in_beside_the_app_is_passed_on() {
        let _guard = serialised();
        let root = tempfile::tempdir().unwrap();
        let bin = root.path().join("bin");
        fs::create_dir_all(&bin).unwrap();
        let name = if cfg!(windows) { "tesseract.exe" } else { "tesseract" };
        fs::write(bin.join(name), "#!/bin/sh\n").unwrap();
        let env = portable_env(Some(root.path()));
        assert_eq!(
            value(&env, "FREEDOCS_TESSERACT"),
            Some(bin.join(name).as_os_str())
        );
    }

    #[test]
    fn an_explicit_choice_is_never_overwritten() {
        let _guard = serialised();
        // Same precedence `FREEDOCS_ENGINE` has: a developer who said where the
        // model is meant it.
        let root = tempfile::tempdir().unwrap();
        model_at(root.path());
        std::env::set_var("FREEDOCS_NER_MODEL", "/chosen");
        let env = portable_env(Some(root.path()));
        std::env::remove_var("FREEDOCS_NER_MODEL");
        assert!(value(&env, "FREEDOCS_NER_MODEL").is_none());
    }

    #[test]
    fn an_engine_that_is_not_there_has_no_build_date() {
        // None rather than zero, and asserted as the decision it is: a zero
        // renders as 1 January 1970, which is a wrong date rather than an absent
        // one, and the window would print it.
        let root = tempfile::tempdir().unwrap();
        let identity = identify(&root.path().join("absent"), Source::Bundled);
        assert_eq!(identity.modified, None);
        assert_ne!(identity.modified, Some(0));
    }

    #[test]
    fn a_build_date_is_read_once_when_the_session_starts() {
        // `Launch` is resolved once on purpose, so the reported identity must
        // describe the process that is serving requests, not whatever is on disk
        // by the time somebody asks.
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("freedocs-engine");
        fs::write(&path, "one").unwrap();
        let identity = identify(&path, Source::Bundled);
        let first = identity.modified;
        assert!(first.is_some());

        std::thread::sleep(std::time::Duration::from_millis(1100));
        fs::write(&path, "two").unwrap();
        assert_eq!(identity.modified, first);
        assert_ne!(identify(&path, Source::Bundled).modified, first);
    }

    #[test]
    fn the_three_routes_are_three_different_words() {
        // A closed vocabulary the window translates by key, pinned so a rename
        // cannot silently leave one locale rendering nothing. Same reasoning as
        // the engine's stage names.
        let words: Vec<String> = [Source::Override, Source::Bundled, Source::Checkout]
            .iter()
            .map(|source| serde_json::to_string(source).unwrap())
            .collect();
        assert_eq!(words, vec!["\"override\"", "\"bundled\"", "\"checkout\""]);
    }
}
