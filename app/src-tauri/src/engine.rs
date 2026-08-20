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

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
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
const REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(600);

pub struct Engine {
    stdin: Mutex<ChildStdin>,
    pending: Mutex<HashMap<u64, Sender<Value>>>,
    next_id: AtomicU64,
    _child: Mutex<Child>,
}

impl Engine {
    pub fn spawn(app: &AppHandle) -> Result<Self, String> {
        let executable = locate(app)?;
        let mut child = Command::new(&executable)
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

        let engine = Engine {
            stdin: Mutex::new(stdin),
            pending: Mutex::new(HashMap::new()),
            next_id: AtomicU64::new(1),
            _child: Mutex::new(child),
        };

        let handle = app.clone();
        std::thread::spawn(move || read_loop(handle, BufReader::new(stdout)));
        Ok(engine)
    }

    /// Send one request and wait for the response with the matching id.
    ///
    /// Blocking, and therefore only ever called from a blocking task: a scrub
    /// with OCR takes seconds and the window must stay alive throughout.
    pub fn request(&self, method: &str, params: Value) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver): (Sender<Value>, Receiver<Value>) = channel();
        self.pending
            .lock()
            .map_err(|_| "the engine lock is poisoned".to_string())?
            .insert(id, sender);

        let request = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        {
            let mut stdin = self
                .stdin
                .lock()
                .map_err(|_| "the engine lock is poisoned".to_string())?;
            writeln!(stdin, "{request}").map_err(|error| format!("engine write failed: {error}"))?;
            stdin
                .flush()
                .map_err(|error| format!("engine flush failed: {error}"))?;
        }

        let response = receiver.recv_timeout(REQUEST_TIMEOUT).map_err(|_| {
            format!("the engine did not answer {method:?} within {REQUEST_TIMEOUT:?}")
        })?;

        if let Some(error) = response.get("error") {
            // Returned as an error string carrying the engine's own structured
            // payload: the app renders "install OCR" differently from "this is a
            // bug", and it can only tell them apart by the code.
            return Err(error.to_string());
        }
        Ok(response.get("result").cloned().unwrap_or(Value::Null))
    }
}

fn read_loop(app: AppHandle, reader: BufReader<std::process::ChildStdout>) {
    for line in reader.lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let Ok(message) = serde_json::from_str::<Value>(&line) else {
            eprintln!("engine sent a line that is not JSON: {line}");
            continue;
        };

        match message.get("id").and_then(Value::as_u64) {
            Some(id) => {
                let sender = app
                    .state::<Arc<Engine>>()
                    .pending
                    .lock()
                    .ok()
                    .and_then(|mut pending| pending.remove(&id));
                if let Some(sender) = sender {
                    let _ = sender.send(message);
                }
            }
            // No id: a notification. Progress and the startup announcement both
            // arrive this way, and both are for the window rather than for a
            // waiting caller.
            None => {
                let _ = app.emit(NOTIFY_EVENT, message);
            }
        }
    }
}

fn locate(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(override_path) = std::env::var("FREEDOCS_ENGINE") {
        let path = PathBuf::from(override_path);
        if path.is_file() {
            return Ok(path);
        }
        return Err(format!("FREEDOCS_ENGINE points at {path:?}, which is not a file"));
    }

    let executable = if cfg!(windows) {
        "freedocs-engine.exe"
    } else {
        "freedocs-engine"
    };
    if let Ok(resources) = app.path().resource_dir() {
        let bundled = resources.join("freedocs-engine").join(executable);
        if bundled.is_file() {
            return Ok(bundled);
        }
    }

    for candidate in dev_candidates() {
        if candidate.is_file() {
            return Ok(candidate);
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
