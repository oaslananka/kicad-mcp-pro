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

/// Desktop/backend API contract negotiated through `/api/health`.
/// This is intentionally independent from the MCP protocol version.
const DESKTOP_API_CONTRACT_VERSION: &str = "1.0.0";
const DESKTOP_BACKEND_VERSION_POLICY: &str = "exact-release";

fn backend_package_spec() -> String {
    format!("kicad-mcp-pro=={}", env!("CARGO_PKG_VERSION"))
}

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

#[derive(Debug, PartialEq, Eq)]
enum BackendProbe {
    Unreachable,
    Compatible,
    Incompatible(String),
}

#[derive(Debug, serde::Deserialize)]
struct BackendHealthPayload {
    version: String,
    #[serde(rename = "desktopCompatibility")]
    desktop_compatibility: Option<DesktopCompatibilityPayload>,
}

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopCompatibilityPayload {
    contract_version: String,
    backend_version: String,
    version_policy: String,
}

fn parse_health_response(response: &str) -> BackendProbe {
    let (headers, body) = match response.split_once("\r\n\r\n") {
        Some(parts) => parts,
        None => {
            return BackendProbe::Incompatible("the health response was not valid HTTP".to_string())
        }
    };
    let status = headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1));
    if status != Some("200") {
        return BackendProbe::Incompatible(format!(
            "the health endpoint returned HTTP {}",
            status.unwrap_or("<missing>")
        ));
    }

    let payload: BackendHealthPayload = match serde_json::from_str(body) {
        Ok(value) => value,
        Err(error) => {
            return BackendProbe::Incompatible(format!(
                "the health endpoint did not return the desktop compatibility contract: {error}"
            ))
        }
    };
    let compatibility = match payload.desktop_compatibility {
        Some(value) => value,
        None => {
            return BackendProbe::Incompatible(
                "the health endpoint omitted desktopCompatibility".to_string(),
            )
        }
    };
    let expected_version = env!("CARGO_PKG_VERSION");
    if payload.version != expected_version || compatibility.backend_version != expected_version {
        return BackendProbe::Incompatible(format!(
            "found backend version {} (contract reports {}), expected {}",
            payload.version, compatibility.backend_version, expected_version
        ));
    }
    if compatibility.contract_version != DESKTOP_API_CONTRACT_VERSION {
        return BackendProbe::Incompatible(format!(
            "found desktop API contract {}, expected {}",
            compatibility.contract_version, DESKTOP_API_CONTRACT_VERSION
        ));
    }
    if compatibility.version_policy != DESKTOP_BACKEND_VERSION_POLICY {
        return BackendProbe::Incompatible(format!(
            "found version policy {}, expected {}",
            compatibility.version_policy, DESKTOP_BACKEND_VERSION_POLICY
        ));
    }
    BackendProbe::Compatible
}

fn probe_backend(port: u16) -> BackendProbe {
    let addr: SocketAddr = match server_addr(port).parse() {
        Ok(value) => value,
        Err(_) => return BackendProbe::Unreachable,
    };
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(750)) {
        Ok(value) => value,
        Err(_) => return BackendProbe::Unreachable,
    };
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
        server_addr(port)
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return BackendProbe::Unreachable;
    }
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return BackendProbe::Unreachable;
    }
    parse_health_response(&response)
}

#[cfg(test)]
fn check_health(port: u16) -> bool {
    matches!(probe_backend(port), BackendProbe::Compatible)
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

fn manual_backend_command(port: u16) -> String {
    format!(
        "uvx --from {} kicad-mcp-pro dashboard --host 127.0.0.1 --port {port}",
        backend_package_spec()
    )
}

fn incompatible_backend_error(port: u16, reason: &str) -> String {
    format!(
        "Incompatible service detected at http://{}/api/health: {}. \
KiCad MCP Pro Desktop {} requires backend {} with desktop API contract {} and {} policy. \
Stop the incompatible service or run the supported backend explicitly: {}",
        server_addr(port),
        reason,
        env!("CARGO_PKG_VERSION"),
        env!("CARGO_PKG_VERSION"),
        DESKTOP_API_CONTRACT_VERSION,
        DESKTOP_BACKEND_VERSION_POLICY,
        manual_backend_command(port),
    )
}

fn start_server_inner(process: &ServerProcess, port: u16) -> Result<String, String> {
    // Clear previous error
    if let Ok(mut err_guard) = process.error.lock() {
        *err_guard = None;
    }

    match probe_backend(port) {
        BackendProbe::Compatible => return Ok("already_running".to_string()),
        BackendProbe::Incompatible(reason) => {
            return Err(incompatible_backend_error(port, &reason));
        }
        BackendProbe::Unreachable => {}
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

    // Release builds launch the backend version that was validated with this
    // exact GUI package. uvx may reuse that exact cached environment offline;
    // it must never fall forward or backward to another release.
    let backend_spec = backend_package_spec();
    let mut cmd = Command::new(&uvx);
    cmd.current_dir(&cwd)
        .args([
            "--from",
            backend_spec.as_str(),
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
        match probe_backend(port) {
            BackendProbe::Compatible => return Ok("started".to_string()),
            BackendProbe::Incompatible(reason) => {
                let _ = stop_server_inner(process);
                return Err(incompatible_backend_error(port, &reason));
            }
            BackendProbe::Unreachable => {}
        }
        // Check if the child process has exited (server crashed)
        if let Ok(mut guard) = process.child.lock() {
            if let Some(ref mut child) = *guard {
                if let Some(status) = child.try_wait().ok().flatten() {
                    let _ = child.wait();
                    drop(guard);
                    return Err(format!(
                        "Python server process exited unexpectedly (code: {}) before binding to port {}.\n\
                         The desktop requires backend {}. Run manually to debug: {}",
                        status.code().map(|c| c.to_string()).unwrap_or_else(|| "signal".to_string()),
                        port,
                        env!("CARGO_PKG_VERSION"),
                        manual_backend_command(port),
                    ));
                }
            }
        }
        thread::sleep(HEALTH_POLL_INTERVAL);
    }

    let _ = stop_server_inner(process);
    Err(format!(
        "Python server at http://{}/api/health did not provide a compatible desktop handshake within {} seconds.\n\
         The desktop requires backend {} and desktop API contract {}. \
If the exact backend is not already cached, network access is required for uvx to obtain it. \
Run manually to debug: {}",
        server_addr(port),
        HEALTH_WAIT.as_secs(),
        env!("CARGO_PKG_VERSION"),
        DESKTOP_API_CONTRACT_VERSION,
        manual_backend_command(port),
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
            let show_item = MenuItemBuilder::with_id("show", "Show Window").build(app)?;
            let quit_item = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    fn serve_health_once(body: String) -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test health server");
        let port = listener.local_addr().expect("test health address").port();
        std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept health probe");
            let mut request = [0_u8; 1024];
            let _ = stream.read(&mut request);
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body,
            );
            stream
                .write_all(response.as_bytes())
                .expect("write health response");
        });
        port
    }

    #[test]
    fn health_probe_accepts_exact_release_and_desktop_contract() {
        let body = format!(
            r#"{{"ok":true,"status":"ok","version":"{}","desktopCompatibility":{{"contractVersion":"1.0.0","backendVersion":"{}","versionPolicy":"exact-release"}}}}"#,
            env!("CARGO_PKG_VERSION"),
            env!("CARGO_PKG_VERSION"),
        );
        let port = serve_health_once(body);
        assert!(check_health(port));
    }

    #[test]
    fn health_probe_rejects_http_200_from_incompatible_backend_version() {
        let body = r#"{"ok":true,"status":"ok","version":"99.0.0","desktopCompatibility":{"contractVersion":"1.0.0","backendVersion":"99.0.0","versionPolicy":"exact-release"}}"#.to_string();
        let port = serve_health_once(body);
        assert!(!check_health(port));
    }

    #[test]
    fn health_probe_rejects_http_200_without_desktop_contract() {
        let body = format!(
            r#"{{"ok":true,"status":"ok","version":"{}"}}"#,
            env!("CARGO_PKG_VERSION")
        );
        let port = serve_health_once(body);
        assert!(!check_health(port));
    }

    #[test]
    fn backend_package_spec_is_exact_and_cache_reusable() {
        let spec = backend_package_spec();
        assert_eq!(
            spec,
            format!("kicad-mcp-pro=={}", env!("CARGO_PKG_VERSION"))
        );
        assert!(!spec.contains(">="));
        assert!(!manual_backend_command(3334).contains("@latest"));
    }

    #[test]
    fn desktop_startup_accepts_supported_existing_backend() {
        let body = format!(
            r#"{{"ok":true,"status":"ok","version":"{}","desktopCompatibility":{{"contractVersion":"1.0.0","backendVersion":"{}","versionPolicy":"exact-release"}}}}"#,
            env!("CARGO_PKG_VERSION"),
            env!("CARGO_PKG_VERSION"),
        );
        let port = serve_health_once(body);
        let process = ServerProcess {
            child: Mutex::new(None),
            error: Mutex::new(None),
            working_dir: Mutex::new(None),
        };

        assert_eq!(
            start_server_inner(&process, port),
            Ok("already_running".to_string())
        );
    }

    #[test]
    fn desktop_startup_rejects_incompatible_existing_backend() {
        let body = r#"{"ok":true,"status":"ok","version":"99.0.0","desktopCompatibility":{"contractVersion":"1.0.0","backendVersion":"99.0.0","versionPolicy":"exact-release"}}"#.to_string();
        let port = serve_health_once(body);
        let process = ServerProcess {
            child: Mutex::new(None),
            error: Mutex::new(None),
            working_dir: Mutex::new(None),
        };

        let error =
            start_server_inner(&process, port).expect_err("incompatible backend must fail closed");
        assert!(error.contains("Incompatible service detected"));
        assert!(error.contains(env!("CARGO_PKG_VERSION")));
        assert!(error.contains(DESKTOP_API_CONTRACT_VERSION));
        assert!(error.contains("kicad-mcp-pro=="));
    }
}
