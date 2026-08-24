//! Tauri commands. Thin on purpose: every decision about what is confidential,
//! what gets removed and what the user is warned about belongs to the engine, and
//! duplicating any of it here would mean two answers that can disagree.

mod engine;

use std::sync::Arc;

use engine::Engine;
use serde_json::Value;
use tauri::{Manager, State};

/// A note on `capabilities/default.json`, which is a JSON file and cannot hold
/// one.
///
/// The two plugins are narrowed to the single command each is used for:
/// `dialog:allow-open` and `opener:allow-reveal-item-in-dir`, replacing the
/// `default` sets that also carried `save`, `ask`, `confirm`, `message`,
/// `open-url` and `open-path`. Free, and checkable — the build fails on a
/// permission name that does not exist.
///
/// `core:default` is deliberately left whole, and the reason is worth stating so
/// nobody narrows it for the look of the thing. What it would defend against is
/// injected JavaScript after a webview compromise — and such JavaScript can
/// already call `engine_request` below, which forwards an arbitrary method and
/// arbitrary params to a process that trusts its caller by design. That is
/// arbitrary file read and write. Narrowing `core:path` next to it is closing a
/// window in a house with no door.
///
/// The door is the one worth fitting, and it is not a permission list: it is
/// either path authorisation here in Rust, or removing the engine's filesystem
/// authority altogether so there is nothing to authorise. The second closes the
/// sandbox gap in `core/sandbox.py` at the same time.
///
/// Forward one request to the engine.
///
/// Async, and the blocking wait happens on a blocking task: a scrub with OCR
/// takes seconds, and doing that on the main thread freezes the window.
///
/// The engine is held in an `Arc` purely so this closure can own a handle to it.
/// The obvious shortcut — transmuting the `State` reference to `'static` — is
/// unsound, and reference counting an object that lives for the whole session
/// costs nothing.
#[tauri::command]
async fn engine_request(
    engine: State<'_, Arc<Engine>>,
    method: String,
    params: Value,
) -> Result<Value, String> {
    let engine = Arc::clone(&engine);
    tauri::async_runtime::spawn_blocking(move || engine.request(&method, params))
        .await
        .map_err(|error| format!("the engine task failed: {error}"))?
}

/// Point WebView2 at a runtime shipped beside the executable, if there is one.
///
/// Windows only, and it has to happen here rather than in `setup`: the WebView2
/// loader reads this variable when it creates the webview, which the builder below
/// does, so a later assignment is a variable nobody reads. That also rules out
/// `resource_dir()` — it needs a built `App` — which is the one reason this
/// resolves its own path instead of sharing `engine::resource_root`.
///
/// The runtime is what makes a portable Windows build work on a machine that
/// installed nothing. Without it the window silently never opens, which is the
/// least diagnosable failure this app has.
#[cfg(windows)]
fn adopt_bundled_webview() {
    const VARIABLE: &str = "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER";
    if std::env::var_os(VARIABLE).is_some() {
        return;
    }
    let Ok(executable) = std::env::current_exe() else {
        return;
    };
    let Some(directory) = executable.parent() else {
        return;
    };
    let runtime = directory.join("webview2");
    // The loader wants the directory holding msedgewebview2.exe. A directory that
    // exists but holds no runtime would make it fail rather than fall back to the
    // installed one, so the check is for the executable and not the folder.
    if runtime.join("msedgewebview2.exe").is_file() {
        std::env::set_var(VARIABLE, runtime);
    }
}

#[cfg(not(windows))]
fn adopt_bundled_webview() {}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    adopt_bundled_webview();
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Spawned once, at startup, so the model is loaded before the user
            // has picked a file rather than after.
            let handle = app.handle().clone();
            match Engine::spawn(&handle) {
                // Already an `Arc`: the reader thread holds one too, so the
                // engine has to be shared before it is managed rather than
                // after. It is also what lets a reader report its own process
                // dying instead of looking the engine up through Tauri state,
                // which was a lookup racing the `manage` below.
                Ok(started) => {
                    app.manage(started);
                }
                Err(error) => {
                    // Not fatal: the window opens and shows the reason. A desktop
                    // app that dies silently because a sidecar is missing is
                    // impossible to diagnose from the user's side.
                    eprintln!("engine unavailable: {error}");
                    app.manage(EngineError(error));
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine_request, engine_status])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Held in state when the engine could not be started, so the window can explain.
struct EngineError(String);

#[tauri::command]
fn engine_status(app: tauri::AppHandle) -> Result<(), String> {
    if app.try_state::<Arc<Engine>>().is_some() {
        return Ok(());
    }
    Err(app
        .try_state::<EngineError>()
        .map(|error| error.0.clone())
        .unwrap_or_else(|| "the engine was never started".to_string()))
}
