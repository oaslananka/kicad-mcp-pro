use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::menu::{MenuBuilder, MenuItemBuilder};

/// Minimum kicad-mcp-pro version the GUI will launch via `uvx --from`.
/// Bump this when the GUI requires a newer backend. The floor must stay at or
/// above the first release whose `dashboard` command binds the HTTP transport
/// (3.11.0); earlier cached builds started the stdio transport instead.
const MIN_BACKEND_SPEC: &str = "kicad-mcp-pro>=3.11.0";

/// How long to wait for the backend to bind and answer /api/health before
/// giving up. First runs download the package and its dependencies via uvx,
/// which can take well over a minute on a cold cache or slow network, so this
/// must be generous — and must not be shorter than the frontend's own poll
/// window, or a still-installing child would be killed prematurely.
const HEALTH_WAIT: Duration = Duration::from_secs(120);
const HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(500);

#[derive(Clone, serde::Serialize)]
pub struct ServerStatus {
    pub running: bool,
    pub message: String,
    pub pid: Option<u32>,
    pub working_dir: Option<String>,
}

pub struct ServerProcess {
    pub child: Mutex<Option<Child>>,
    pub error: Mutex<Option<String>>,
    pub working_dir: Mutex<Option<PathBuf>>,
}

impl Drop for ServerProcess {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn server_addr(port: u16) -> String {
    format!("127.0.0.1:{port}")
}

fn check_health(port: u16) -> bool {
    let addr: SocketAddr = match server_addr(port).parse() {
        Ok(value) => value,
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(750)) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
        server_addr(port)
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    response.contains("200 OK")
}

fn which_uvx() -> Option<PathBuf> {
    if let Ok(path) = which::which("uvx") {
        return Some(path);
    }
    #[cfg(windows)]
    {
        if let Some(home) = std::env::var_os("USERPROFILE") {
            // uv installed via cargo: ~/.cargo/bin/uvx.exe
            let candidate = PathBuf::from(&home)
                .join(".cargo")
                .join("bin")
                .join("uvx.exe");
            if candidate.exists() {
                return Some(candidate);
            }
            // uv installed via official installer (irm https://astral.sh/uv/install.ps1): ~/.local/bin/uvx.exe
            let candidate = PathBuf::from(&home)
                .join(".local")
                .join("bin")
                .join("uvx.exe");
            if candidate.exists() {
                return Some(candidate);
            }
        }
        // Also check common uv install locations on Windows
        for base in ["LOCALAPPDATA", "APPDATA"] {
            if let Some(var) = std::env::var_os(base) {
                let candidate = PathBuf::from(var).join("uv").join("uvx.exe");
                if candidate.exists() {
                    return Some(candidate);
                }
            }
        }
    }
    None
}

fn start_server_inner(process: &ServerProcess, port: u16) -> Result<String, String> {
    // Clear previous error
    if let Ok(mut err_guard) = process.error.lock() {
        *err_guard = None;
    }

    if check_health(port) {
        return Ok("already_running".to_string());
    }

    let mut guard = process.child.lock().map_err(|error| error.to_string())?;
    if guard
        .as_mut()
        .is_some_and(|child| child.try_wait().ok().flatten().is_none())
    {
        return Ok("already_running".to_string());
    }
    if guard.is_some() {
        *guard = None;
    }

    let uvx = which_uvx().ok_or_else(|| {
        let hint = if cfg!(target_os = "windows") {
            "Install uv from PowerShell: (irm https://astral.sh/uv/install.ps1) | iex"
        } else {
            "Install uv: curl -fsSL https://astral.sh/uv/install.sh | sh"
        };
        format!("uvx was not found. {hint}")
    })?;
    // Use user-selected working directory (if set), or fall back to HOME
    let cwd = process
        .working_dir
        .lock()
        .ok()
        .and_then(|guard| guard.clone())
        .or_else(|| {
            std::env::var_os("USERPROFILE")
                .map(PathBuf::from)
                .or_else(|| std::env::var_os("HOME").map(PathBuf::from))
        })
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

    // Log to a file for debugging (especially useful when spawned from Tauri GUI)
    let log_dir = std::env::var_os("TEMP")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    let log_path = log_dir.join("kicad-mcp-pro-server.log");
    let log_file = std::fs::File::create(&log_path)
        .map_err(|e| format!("Failed to create server log {log_path:?}: {e}"))?;

    // Pin a minimum backend version with `--from` so uvx cannot serve a stale
    // cached build. Older cached versions (e.g. 3.9.0) shipped a `dashboard`
    // command that fell back to the stdio transport and never bound the HTTP
    // port, which surfaced in the GUI as "Server failed to start". `>=` lets
    // uvx reuse a satisfying cached environment (fast, works offline) while
    // refusing anything below the known-good floor.
    let mut cmd = Command::new(&uvx);
    cmd.current_dir(&cwd)
        .args([
            "--from",
            MIN_BACKEND_SPEC,
            "kicad-mcp-pro",
            "dashboard",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ])
        .stdout(Stdio::null())
        .stderr(log_file)
        .stdin(Stdio::null());

    #[cfg(windows)]
    {
        // Prevent the console-mode uvx.exe from opening a cmd window
        // when spawned from a Windows-subsystem (GUI) Tauri app.
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    let child = cmd
        .spawn()
        .map_err(|error| format!("Failed to start kicad-mcp-pro with {uvx:?}: {error}"))?;

    *guard = Some(child);
    drop(guard);

    // Wait for the server to become healthy. The first launch downloads the
    // package via uvx, so allow a generous window (HEALTH_WAIT) before giving
    // up — killing the child early would abort an install that is still in
    // progress.
    let deadline = std::time::Instant::now() + HEALTH_WAIT;
    while std::time::Instant::now() < deadline {
        if check_health(port) {
            return Ok("started".to_string());
        }
        // Check if the child process has exited (server crashed)
        if let Ok(mut guard) = process.child.lock() {
            if let Some(ref mut child) = *guard {
                if let Some(status) = child.try_wait().ok().flatten() {
                    let _ = child.wait();
                    drop(guard);
                    return Err(format!(
                        "Python server process exited unexpectedly (code: {}) before binding to port {}.\n\
                         Run manually to debug: uvx kicad-mcp-pro@latest dashboard --host 127.0.0.1 --port {port}",
                        status.code().map(|c| c.to_string()).unwrap_or_else(|| "signal".to_string()),
                        port,
                    ));
                }
            }
        }
        thread::sleep(HEALTH_POLL_INTERVAL);
    }

    let _ = stop_server_inner(process);
    Err(format!(
        "Python server at http://{}/api/health did not respond within {} seconds.\n\
         First runs download the backend and can be slow. Run manually to debug: uvx kicad-mcp-pro@latest dashboard --host 127.0.0.1 --port {port}",
        server_addr(port),
        HEALTH_WAIT.as_secs(),
    ))
}

fn stop_server_inner(process: &ServerProcess) -> Result<(), String> {
    let mut guard = process.child.lock().map_err(|error| error.to_string())?;
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    Ok(())
}

#[tauri::command]
fn start_server(state: State<'_, ServerProcess>, port: u16) -> Result<String, String> {
    start_server_inner(state.inner(), port)
}

#[tauri::command]
fn stop_server(state: State<'_, ServerProcess>) -> Result<(), String> {
    stop_server_inner(state.inner())
}

#[tauri::command]
fn server_pid(state: State<'_, ServerProcess>) -> Option<u32> {
    state
        .inner()
        .child
        .lock()
        .ok()?
        .as_ref()
        .map(|child| child.id())
}

#[tauri::command]
fn server_status(state: State<'_, ServerProcess>) -> ServerStatus {
    let pid = state
        .inner()
        .child
        .lock()
        .ok()
        .and_then(|guard| guard.as_ref().map(|child| child.id()));
    let running = pid.is_some();
    let error_msg = state
        .inner()
        .error
        .lock()
        .ok()
        .and_then(|guard| guard.clone());
    let wd = state
        .inner()
        .working_dir
        .lock()
        .ok()
        .and_then(|guard| guard.clone())
        .map(|p| p.to_string_lossy().to_string());
    ServerStatus {
        running,
        message: error_msg.unwrap_or_else(|| {
            if running {
                "Server is running.".to_string()
            } else {
                "Server is not running.".to_string()
            }
        }),
        pid,
        working_dir: wd,
    }
}

/// Opens a native OS folder-picker dialog and stores the selection
/// as the working directory for the Python server process.
#[tauri::command]
fn select_working_dir(
    app: tauri::AppHandle,
    state: State<'_, ServerProcess>,
) -> Result<String, String> {
    let path = app
        .dialog()
        .file()
        .blocking_pick_folder()
        .ok_or_else(|| "No folder selected.".to_string())?;
    let path_str = path.to_string();
    let path_buf = path
        .as_path()
        .ok_or_else(|| "Selected path is not a valid filesystem path.".to_string())?
        .to_path_buf();
    if let Ok(mut guard) = state.working_dir.lock() {
        *guard = Some(path_buf);
    }
    eprintln!("[kicad-mcp-pro] Working directory set to: {path_str}");
    Ok(path_str)
}

/// Returns the currently selected working directory, if any.
#[tauri::command]
fn get_working_dir(state: State<'_, ServerProcess>) -> Option<String> {
    state
        .inner()
        .working_dir
        .lock()
        .ok()
        .and_then(|guard| guard.clone())
        .map(|p| p.to_string_lossy().to_string())
}

/// Stops the running server (if any) and restarts it with the
/// current settings (port, working directory, etc.).
#[tauri::command]
fn restart_server(state: State<'_, ServerProcess>, port: u16) -> Result<String, String> {
    let _ = stop_server_inner(state.inner());
    // Give the OS a moment to release the port
    thread::sleep(Duration::from_millis(500));
    start_server_inner(state.inner(), port)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(ServerProcess {
            child: Mutex::new(None),
            error: Mutex::new(None),
            working_dir: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            start_server,
            stop_server,
            server_pid,
            server_status,
            select_working_dir,
            get_working_dir,
            restart_server,
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // Close-to-tray: hide window instead of quitting.
                // Use tray menu "Quit" to fully exit.
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .setup(|app| {
            // Build tray context menu
            let show_item = MenuItemBuilder::with_id("show", "Show Window")
                .build(app)?;
            let quit_item = MenuItemBuilder::with_id("quit", "Quit")
                .build(app)?;
            let menu = MenuBuilder::new(app)
                .item(&show_item)
                .separator()
                .item(&quit_item)
                .build()?;

            let mut tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("KiCad MCP Pro - Starting...")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| {
                    match event.id().as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "quit" => {
                            // Stop the server first
                            if let Some(state) = app.try_state::<ServerProcess>() {
                                let _ = stop_server_inner(state.inner());
                            }
                            app.exit(0);
                        }
                        _ => {}
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            let _ = tray.build(app)?;

            // Launch the backend on a background thread so the first-run
            // download (which can take up to HEALTH_WAIT) never blocks the UI
            // or the tray. The frontend polls /api/health and server_status
            // independently and redirects as soon as the server is ready.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let state = handle.state::<ServerProcess>();
                match start_server_inner(state.inner(), 3334) {
                    Ok(status) => {
                        eprintln!("[kicad-mcp-pro] Server started: {status}");
                        let _ = state.error.lock().map(|mut e| *e = None);
                    }
                    Err(error) => {
                        eprintln!("[kicad-mcp-pro] ERROR: {error}");
                        let _ = state.error.lock().map(|mut e| *e = Some(error));
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Failed to start KiCad MCP Pro Tauri app");
}
