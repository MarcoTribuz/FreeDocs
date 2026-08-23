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
        let mut command = Command::new(&executable);
        for (name, value) in portable_env(resource_root(app).as_deref()) {
            command.env(name, value);
        }
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
/// So an installer build, where none of these exist, hands the engine an
/// unchanged environment and behaves exactly as it did before this existed.
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

    // Nothing ships one: PyMuPDF shells out to Tesseract, so the binary is a
    // platform package and cannot be bundled. This is the hook that lets a user
    // drop one in beside the app without a rebuild, and the engine validates it
    // before believing it.
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
    if let Some(resources) = resource_root(app) {
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

#[cfg(test)]
mod tests {
    //! `portable_env` only, because it is the only new thing here with a
    //! decision in it. Everything around it needs a running `AppHandle`, and a
    //! test that builds one tests Tauri.

    use super::{has_traineddata, portable_env};
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
}
