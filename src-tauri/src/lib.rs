use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::ops::{Deref, DerefMut};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::ShellExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::menu::{MenuBuilder, MenuItemBuilder};

#[cfg(windows)]
mod backend_job;

/// A desktop-owned backend with its Windows subprocess tree. Stopping uvx
/// alone does not stop its uv/python descendants on Windows.
struct ManagedBackend {
    child: Child,
    #[cfg(windows)]
    job: Option<backend_job::WindowsJob>,
}

impl ManagedBackend {
    fn spawn(command: &mut Command) -> std::io::Result<Self> {
        let child = command.spawn()?;
        #[cfg(windows)]
        let job = match backend_job::WindowsJob::attach(&child) {
            Ok(job) => Some(job),
            Err(error) => {
                let mut child = child;
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        Ok(Self {
            child,
            #[cfg(windows)]
            job,
        })
    }

    fn shutdown(&mut self) {
        #[cfg(windows)]
        if let Some(job) = self.job.take() {
            // The last KILL_ON_JOB_CLOSE handle also kills descendants if
            // explicit termination fails. This never targets user PIDs.
            job.terminate();
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Deref for ManagedBackend {
    type Target = Child;
    fn deref(&self) -> &Child {
        &self.child
    }
}
impl DerefMut for ManagedBackend {
    fn deref_mut(&mut self) -> &mut Child {
        &mut self.child
    }
}
impl Drop for ManagedBackend {
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// Desktop/backend API contract negotiated through `/api/health`.
/// This is intentionally independent from the MCP protocol version.
const DESKTOP_API_CONTRACT_VERSION: &str = "1.0.0";
const DESKTOP_BACKEND_VERSION_POLICY: &str = "exact-release";

// User-authorized second loopback port if the default is already occupied by
// an older KiCad MCP or another application. Never take over that service.
const PRIMARY_DASHBOARD_PORT: u16 = 3334;
const SEPARATE_DASHBOARD_PORT: u16 = 3335;

fn supported_dashboard_port(port: u16) -> bool {
    matches!(port, PRIMARY_DASHBOARD_PORT | SEPARATE_DASHBOARD_PORT)
}

fn backend_package_spec() -> String {
    format!("kicad-mcp-pro=={}", env!("CARGO_PKG_VERSION"))
}

/// How long to wait for the backend to bind and answer /api/health before
/// giving up. First runs download the package and its dependencies via uvx,
/// which can take well over a minute on a cold cache or slow network, so this
/// must be generous — and must not be shorter than the frontend's own poll
/// window, or a still-installing child would be killed prematurely.
const HEALTH_WAIT: Duration = Duration::from_secs(300);
const HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(500);

#[derive(Clone, serde::Serialize)]
pub struct ServerStatus {
    pub running: bool,
    pub message: String,
    pub pid: Option<u32>,
    pub working_dir: Option<String>,
    pub preparation_stage: String,
    pub runtime_found: bool,
}

pub struct ServerProcess {
    pub(crate) child: Mutex<Option<ManagedBackend>>,
    /// Bundled pinned uv runtime, independent from the user's global Python.
    pub bundled_uv: Mutex<Option<PathBuf>>,
    pub error: Mutex<Option<String>>,
    pub working_dir: Mutex<Option<PathBuf>>,
    pub preparation_stage: Mutex<String>,
    /// Selected through the native splash, never from arbitrary HTTP content.
    pub dashboard_port: Mutex<u16>,
}

impl ServerProcess {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            bundled_uv: Mutex::new(None),
            error: Mutex::new(None),
            working_dir: Mutex::new(None),
            preparation_stage: Mutex::new("idle".to_string()),
            dashboard_port: Mutex::new(PRIMARY_DASHBOARD_PORT),
        }
    }
}

impl Default for ServerProcess {
    fn default() -> Self {
        Self::new()
    }
}

fn set_stage(process: &ServerProcess, stage: &str) {
    if let Ok(mut g) = process.preparation_stage.lock() {
        *g = stage.to_string();
    }
}

fn get_stage(process: &ServerProcess) -> String {
    process
        .preparation_stage
        .lock()
        .map(|g| g.clone())
        .unwrap_or_else(|_| "idle".to_string())
}

fn selected_dashboard_port(process: &ServerProcess) -> Result<u16, String> {
    process
        .dashboard_port
        .lock()
        .map(|port| *port)
        .map_err(|_| "Desktop port state is unavailable.".to_string())
}

impl Drop for ServerProcess {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                child.shutdown();
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

fn user_runtime_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        std::env::var_os("LOCALAPPDATA")
            .map(|b| PathBuf::from(b).join("kicad-mcp-pro").join("runtime"))
    }
    #[cfg(not(windows))]
    {
        std::env::var_os("HOME").map(|b| {
            PathBuf::from(b)
                .join(".local")
                .join("share")
                .join("kicad-mcp-pro")
                .join("runtime")
        })
    }
}

fn desktop_uv(process: &ServerProcess) -> Option<PathBuf> {
    let packaged = process
        .bundled_uv
        .lock()
        .ok()
        .and_then(|value| value.clone());
    if let Some(path) = packaged {
        if path.is_file() {
            return Some(path);
        }
    }
    // Local source development may continue using installed uvx. Release
    // bundles must carry their own reviewed, pinned bootstrap executable.
    if cfg!(debug_assertions) {
        which::which("uv").ok()
    } else {
        None
    }
}

fn manual_backend_command(port: u16) -> String {
    format!(
        "uv tool run --from {} kicad-mcp-pro dashboard --host 127.0.0.1 --port {port}",
        backend_package_spec()
    )
}

/// A read-only desktop/loopback compatibility probe. The WebView must not
/// infer readiness from an opaque (no-cors) HTTP response from another app.
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopReadiness {
    ready: bool,
    incompatible: bool,
    detail: String,
    expected_version: String,
    port: u16,
}

#[tauri::command]
fn desktop_readiness(state: State<'_, ServerProcess>) -> DesktopReadiness {
    let (port, ready, incompatible, detail) = match selected_dashboard_port(state.inner()) {
        Ok(port) if supported_dashboard_port(port) => match probe_backend(port) {
            BackendProbe::Compatible => (
                port,
                true,
                false,
                "Verified exact-version desktop backend".to_string(),
            ),
            BackendProbe::Unreachable => (
                port,
                false,
                false,
                "Waiting for exact-version backend".to_string(),
            ),
            BackendProbe::Incompatible(reason) => (port, false, true, reason),
        },
        _ => (
            0,
            false,
            true,
            "Desktop port state is unavailable.".to_string(),
        ),
    };
    DesktopReadiness {
        ready,
        incompatible,
        detail,
        expected_version: env!("CARGO_PKG_VERSION").to_string(),
        port,
    }
}

#[tauri::command]
fn desktop_backend_command(state: State<'_, ServerProcess>) -> String {
    manual_backend_command(selected_dashboard_port(state.inner()).unwrap_or(PRIMARY_DASHBOARD_PORT))
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
    // Native commands restrict user-selected ports. The internal helper also
    // supports ephemeral ports in isolated unit tests. Navigation always
    // refuses a port outside the two desktop ports.
    // The active port is used both for the exact-version readiness probe and
    // for the WebView's strictly-scoped loopback navigation permission.
    *process
        .dashboard_port
        .lock()
        .map_err(|_| "Desktop port state is unavailable.".to_string())? = port;
    // Clear previous error
    if let Ok(mut err_guard) = process.error.lock() {
        *err_guard = None;
    }
    set_stage(process, "checking_prerequisites");

    match probe_backend(port) {
        BackendProbe::Compatible => {
            set_stage(process, "ready");
            return Ok("already_running".to_string());
        }
        BackendProbe::Incompatible(reason) => {
            set_stage(process, "failed");
            return Err(incompatible_backend_error(port, &reason));
        }
        BackendProbe::Unreachable => {}
    }

    let mut guard = process.child.lock().map_err(|error| error.to_string())?;
    if guard
        .as_mut()
        .is_some_and(|child| child.try_wait().ok().flatten().is_none())
    {
        return Err("Server startup is already in progress.".to_string());
    }
    if guard.is_some() {
        *guard = None;
    }

    set_stage(process, "preparing_environment");
    let uvx = desktop_uv(process).ok_or_else(|| {
        set_stage(process, "failed");
        "The application-owned Python bootstrap is missing. Repair or reinstall the official KiCad MCP Pro desktop package; your KiCad projects are unchanged."
            .to_string()
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
    // Keep Python and downloaded dependencies in app-owned user storage;
    // do not modify system Python, uv settings or shared package caches.
    if let Some(runtime) = user_runtime_dir() {
        std::fs::create_dir_all(&runtime)
            .map_err(|_| "Could not prepare private desktop runtime storage.".to_string())?;
        cmd.env("KICAD_MCP_DESKTOP_UV", &uvx)
            .env("UV_CACHE_DIR", runtime.join("cache"))
            .env("UV_PYTHON_INSTALL_DIR", runtime.join("python"))
            .env("UV_PYTHON_PREFERENCE", "only-managed")
            // Keep the managed runtime on a supported Python minor release.
            // Unconstrained uv selected 3.15 and cold Windows install took
            // longer than the prior 120-second splash timeout.
            .env("UV_PYTHON", "3.13")
            .env("UV_NO_CONFIG", "1")
            .env("UV_NO_PROGRESS", "1");
    }
    cmd.current_dir(&cwd)
        .args([
            "tool",
            "run",
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

    let child = ManagedBackend::spawn(&mut cmd).map_err(|error| {
        set_stage(process, "failed");
        format!("Failed to start kicad-mcp-pro with {uvx:?}: {error}")
    })?;

    *guard = Some(child);
    drop(guard);

    set_stage(process, "starting_server");
    // Wait for the server to become healthy. The first launch downloads the
    // package via bundled uv, so allow a generous window (HEALTH_WAIT) before giving
    // up — killing the child early would abort an install that is still in
    // progress.
    let deadline = std::time::Instant::now() + HEALTH_WAIT;
    while std::time::Instant::now() < deadline {
        if get_stage(process) == "cancelled" {
            let _ = stop_server_inner(process);
            return Err("Server startup was cancelled.".to_string());
        }
        match probe_backend(port) {
            BackendProbe::Compatible => {
                set_stage(process, "ready");
                return Ok("started".to_string());
            }
            BackendProbe::Incompatible(reason) => {
                set_stage(process, "failed");
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
                    let exited = guard.take();
                    drop(guard);
                    drop(exited);
                    set_stage(process, "failed");
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

    set_stage(process, "failed");
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
        child.shutdown();
    }
    Ok(())
}

/// Restrict the native WebView to its bundled splash and the one local
/// dashboard port selected by the user, never an arbitrary loopback service.
fn allowed_desktop_navigation(url: &tauri::Url, selected_port: Option<u16>) -> bool {
    if matches!(url.scheme(), "http" | "https") && url.host_str() == Some("tauri.localhost") {
        return true;
    }
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && selected_port.is_some_and(|port| {
            supported_dashboard_port(port) && url.port_or_known_default() == Some(port)
        })
}

/// Static outbound destinations usable from the packaged desktop and local UI.
fn allowed_external_link(url: &str) -> bool {
    matches!(
        url,
        "https://github.com/sponsors/oaslananka"
            | "https://www.buymeacoffee.com/oaslananka"
            | "https://oaslananka.github.io/kicad-mcp-pro/agents/"
            | "https://oaslananka.github.io/kicad-mcp-pro/agents/prompts/"
            | "https://kicad-mcp-pro.oaslananka.dev/sign-in"
    )
}

#[tauri::command]
fn open_external_link(app: tauri::AppHandle, url: String) -> Result<(), String> {
    if !allowed_external_link(&url) {
        return Err("External destination is not permitted.".to_string());
    }
    #[allow(deprecated)]
    app.shell()
        .open(url, None)
        .map_err(|_| "Could not open the system browser.".to_string())
}

#[tauri::command]
fn start_server(state: State<'_, ServerProcess>, port: u16) -> Result<String, String> {
    if !supported_dashboard_port(port) {
        return Err("Unsupported desktop port.".to_string());
    }
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
        preparation_stage: get_stage(state.inner()),
        runtime_found: user_runtime_dir().map(|r| r.exists()).unwrap_or(false),
    }
}

#[tauri::command]
fn cancel_server_preparation(state: State<'_, ServerProcess>) -> Result<(), String> {
    set_stage(state.inner(), "cancelled");
    stop_server_inner(state.inner())
}

#[derive(Default)]
struct PendingUpdate(Mutex<(Option<tauri_plugin_updater::Update>, Option<Vec<u8>>)>);

#[derive(serde::Serialize)]
struct UpdateStatus {
    version: Option<String>,
    downloaded: bool,
}

#[tauri::command]
fn update_status(state: State<'_, PendingUpdate>) -> Result<UpdateStatus, String> {
    let pending = state.0.lock().map_err(|e| e.to_string())?;
    Ok(UpdateStatus {
        version: pending.0.as_ref().map(|u| u.version.clone()),
        downloaded: pending.1.is_some(),
    })
}

#[tauri::command]
async fn check_update(app: tauri::AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_updater::UpdaterExt;
    let config: serde_json::Value =
        serde_json::from_str(include_str!("../tauri.conf.json")).map_err(|e| e.to_string())?;
    if config["plugins"]["updater"]["pubkey"]
        .as_str()
        .unwrap_or("")
        .is_empty()
    {
        return Err("Update signing is not configured for this build.".to_string());
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?;
    let version = update.as_ref().map(|u| u.version.clone());
    *app.state::<PendingUpdate>()
        .0
        .lock()
        .map_err(|e| e.to_string())? = (update, None);
    Ok(version)
}

#[tauri::command]
async fn download_update(app: tauri::AppHandle) -> Result<(), String> {
    let update = app
        .state::<PendingUpdate>()
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .0
        .clone()
        .ok_or("No update is available.")?;
    let bytes = update
        .download(|_, _| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    let state = app.state::<PendingUpdate>();
    let mut pending = state.0.lock().map_err(|e| e.to_string())?;
    if pending.0.as_ref().map(|u| &u.version) != Some(&update.version) {
        return Err("Update changed during download. Check again.".to_string());
    }
    pending.1 = Some(bytes);
    Ok(())
}

async fn resume_backend(
    client: &reqwest::Client,
    base: &str,
    cookie: &str,
    csrf: &str,
    maintenance_lease: &str,
) -> Result<(), String> {
    let body = serde_json::json!({"token": maintenance_lease});
    let response = client
        .post(format!("{base}/api/maintenance/resume"))
        .header(reqwest::header::ORIGIN, base)
        .header(reqwest::header::COOKIE, cookie)
        .header("X-KiCad-Owner-CSRF", csrf)
        .json(&body)
        .send()
        .await
        .map_err(|_| "Could not resume backend; restart the desktop to recover.")?;
    if !response.status().is_success() {
        return Err("Backend remains in maintenance; restart the desktop to recover.".into());
    }
    Ok(())
}

async fn quiesce_backend(base: &str) -> Result<(reqwest::Client, String, String, String), String> {
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;
    let response = client
        .get(format!("{base}/api/owner/session"))
        .send()
        .await
        .map_err(|_| "Could not establish local owner session.")?;
    if !response.status().is_success() {
        return Err("Local owner session was rejected.".into());
    }
    let cookie = response
        .headers()
        .get_all(reqwest::header::SET_COOKIE)
        .iter()
        .filter_map(|h| h.to_str().ok())
        .filter_map(|h| h.split(';').next())
        .find(|h| h.starts_with("kicad_owner_session="))
        .ok_or("Owner cookie missing.")?
        .to_string();
    let body: serde_json::Value = response
        .json()
        .await
        .map_err(|_| "Invalid owner session.")?;
    let csrf = body["csrf_token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("Owner token missing.")?
        .to_string();
    let result: Result<String, String> = async {
        let response = client
            .post(format!("{base}/api/maintenance/quiesce"))
            .header(reqwest::header::ORIGIN, base)
            .header(reqwest::header::COOKIE, &cookie)
            .header("X-KiCad-Owner-CSRF", &csrf)
            .json(&serde_json::json!({}))
            .send()
            .await
            .map_err(|_| "Could not quiesce local backend.")?;
        if !response.status().is_success() {
            return Err("Backend is busy or refused maintenance.".into());
        }
        let body: serde_json::Value = response
            .json()
            .await
            .map_err(|_| "Invalid maintenance response.")?;
        if body["ok"] != true || body["state"] != "quiesced" {
            return Err("Backend did not enter maintenance.".into());
        }
        Ok(body["token"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or("Maintenance token missing.")?
            .to_string())
    }
    .await;
    // A failed/ambiguous quiesce never grants us a lease token. Do not
    // attempt a tokenless resume or claim that a safe update transition ran.
    let token = result.map_err(|error| {
        format!("{error} No update was installed. Verify backend state before retrying.")
    })?;
    Ok((client, cookie, csrf, token))
}

#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let (update, bytes) = {
        let state = app.state::<PendingUpdate>();
        let pending = state.0.lock().map_err(|e| e.to_string())?;
        (
            pending.0.clone().ok_or("No update is available.")?,
            pending
                .1
                .clone()
                .ok_or("Download the signed update first.")?,
        )
    };
    {
        let state = app.state::<ServerProcess>();
        let mut child = state.child.lock().map_err(|e| e.to_string())?;
        if !child
            .as_mut()
            .is_some_and(|c| matches!(c.try_wait(), Ok(None)))
        {
            return Err("Installation requires the app-owned backend.".into());
        }
    }
    let port = {
        let process = app.state::<ServerProcess>();
        selected_dashboard_port(process.inner())?
    };
    if !supported_dashboard_port(port) || !matches!(probe_backend(port), BackendProbe::Compatible) {
        return Err("Backend is not ready.".into());
    }
    // A user-selected isolated desktop backend must be quiesced on its own
    // port; the older, independently running service on 3334 is never touched.
    let base = format!("http://{}", server_addr(port));
    let (client, cookie, csrf, token) = quiesce_backend(&base).await?;
    if let Err(error) = update.install(&bytes) {
        resume_backend(&client, &base, &cookie, &csrf, &token).await?;
        return Err(error.to_string());
    }
    Ok(())
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
    // Do not allow web content to choose an arbitrary loopback target.
    if !supported_dashboard_port(port) {
        return Err("Unsupported desktop port.".to_string());
    }
    let _ = stop_server_inner(state.inner());
    // Give the OS a moment to release the port
    thread::sleep(Duration::from_millis(500));
    start_server_inner(state.inner(), port)
}

/// Bring an already-running desktop instance to the foreground.
fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Schedule slow update polling and backend startup without blocking the tray.
fn spawn_background_checks(app_handle: tauri::AppHandle) {
    let updater_handle = app_handle.clone();
    std::thread::spawn(move || loop {
        if matches!(probe_backend(3334), BackendProbe::Compatible) {
            let result = tauri::async_runtime::block_on(check_update(updater_handle.clone()));
            if let Ok(Some(version)) = result {
                eprintln!("[kicad-mcp-pro] Update available: {version}");
            }
            thread::sleep(Duration::from_secs(24 * 60 * 60));
        } else {
            thread::sleep(HEALTH_POLL_INTERVAL);
        }
    });

    // Launch the backend on a background thread so the first-run
    // download (which can take up to HEALTH_WAIT) never blocks the UI
    // or the tray. The frontend polls /api/health and server_status
    // independently and redirects as soon as the server is ready.
    let handle = app_handle;
    std::thread::spawn(move || {
        let state = handle.state::<ServerProcess>();
        match start_server_inner(state.inner(), PRIMARY_DASHBOARD_PORT) {
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
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();
    // Register this first: a second launch must not start another backend
    // process or create another system-tray icon.
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        show_main_window(app);
    }));
    builder
        // The bundled splash has native IPC; the HTTP dashboard intentionally
        // does NOT receive privileged Tauri IPC capabilities. Accept only
        // exact allowlisted external navigation and open it in the OS browser.
        .plugin(
            tauri::plugin::Builder::<_, ()>::new("desktop-external-navigation")
                .on_navigation(|webview, url| {
                    if allowed_external_link(url.as_str()) {
                        #[allow(deprecated)]
                        let _ = webview.app_handle().shell().open(url.to_string(), None);
                        return false;
                    }
                    let selected_port = webview
                        .app_handle()
                        .try_state::<ServerProcess>()
                        .and_then(|state| selected_dashboard_port(state.inner()).ok());
                    allowed_desktop_navigation(url, selected_port)
                })
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(ServerProcess::new())
        .manage(PendingUpdate::default())
        .invoke_handler(tauri::generate_handler![
            start_server,
            stop_server,
            server_pid,
            server_status,
            select_working_dir,
            get_working_dir,
            restart_server,
            desktop_readiness,
            desktop_backend_command,
            open_external_link,
            cancel_server_preparation,
            check_update,
            download_update,
            install_update,
            update_status,
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
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                })
                .on_menu_event(|app, event| {
                    match event.id().as_ref() {
                        "show" => show_main_window(app),
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

            // Tauri resolves the platform-specific installed resource path.
            let executable = if cfg!(windows) { "uv.exe" } else { "uv" };
            if let Ok(resource) = app.path().resolve(
                format!("bootstrap/{executable}"),
                tauri::path::BaseDirectory::Resource,
            ) {
                if resource.is_file() {
                    if let Ok(mut slot) = app.state::<ServerProcess>().bundled_uv.lock() {
                        *slot = Some(resource);
                    }
                }
            }
            spawn_background_checks(app.handle().clone());
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
    fn displayed_backend_command_uses_exact_release_package() {
        let command = manual_backend_command(PRIMARY_DASHBOARD_PORT);
        assert!(command.contains(&format!("kicad-mcp-pro=={}", env!("CARGO_PKG_VERSION"))));
        assert!(!command.contains("@latest"));
        assert!(command.contains("--host 127.0.0.1 --port 3334"));
    }

    #[test]
    fn separate_port_only_allows_the_explicit_local_dashboard() {
        let url = |value: &str| tauri::Url::parse(value).expect("valid URL");
        let primary = url("http://127.0.0.1:3334/ui?desktop=1");
        let alternate = url("http://127.0.0.1:3335/ui?desktop=1");
        assert!(allowed_desktop_navigation(
            &primary,
            Some(PRIMARY_DASHBOARD_PORT)
        ));
        assert!(!allowed_desktop_navigation(
            &alternate,
            Some(PRIMARY_DASHBOARD_PORT)
        ));
        assert!(allowed_desktop_navigation(
            &alternate,
            Some(SEPARATE_DASHBOARD_PORT)
        ));
        assert!(!allowed_desktop_navigation(
            &primary,
            Some(SEPARATE_DASHBOARD_PORT)
        ));
        assert!(!allowed_desktop_navigation(&alternate, None));
        assert!(!allowed_desktop_navigation(
            &url("http://127.0.0.1:4444/ui"),
            Some(SEPARATE_DASHBOARD_PORT)
        ));
        assert!(!allowed_desktop_navigation(
            &url("http://localhost:3335/ui"),
            Some(SEPARATE_DASHBOARD_PORT)
        ));
        assert!(!allowed_desktop_navigation(
            &url("http://attacker.example/ui"),
            Some(SEPARATE_DASHBOARD_PORT)
        ));
        assert!(!allowed_desktop_navigation(
            &url("https://127.0.0.1:3335/ui"),
            Some(SEPARATE_DASHBOARD_PORT)
        ));
        assert!(allowed_desktop_navigation(
            &url("http://tauri.localhost/index.html"),
            Some(PRIMARY_DASHBOARD_PORT)
        ));
        assert!(!supported_dashboard_port(3336));
        assert!(!supported_dashboard_port(0));
        assert!(!supported_dashboard_port(65535));
    }

    #[test]
    fn separate_port_diagnostics_require_the_exact_backend_version() {
        let cmd = manual_backend_command(SEPARATE_DASHBOARD_PORT);
        assert!(cmd.contains(" --host 127.0.0.1 --port 3335"));
        assert!(cmd.contains(&format!("kicad-mcp-pro=={}", env!("CARGO_PKG_VERSION"))));
        assert!(!cmd.contains("@latest"));
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
    fn external_browser_links_are_exactly_allowlisted() {
        assert!(allowed_external_link(
            "https://github.com/sponsors/oaslananka"
        ));
        assert!(allowed_external_link(
            "https://www.buymeacoffee.com/oaslananka"
        ));
        assert!(allowed_external_link(
            "https://kicad-mcp-pro.oaslananka.dev/sign-in"
        ));
        assert!(!allowed_external_link("https://www.buymeacoffee.com/other"));
        assert!(!allowed_external_link(
            "https://github.com/sponsors/oaslananka?other=1"
        ));
        assert!(!allowed_external_link("http://localhost:3334/"));
        assert!(!allowed_external_link(""));
    }

    #[test]
    fn desktop_prefers_packaged_uv_to_global_tools() {
        let process = ServerProcess::new();
        // This test needs a deterministic existing file path only: it never
        // executes, modifies, or launches it.
        let existing = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml");
        assert!(existing.is_file());
        *process.bundled_uv.lock().expect("runtime lock") = Some(existing.clone());
        assert_eq!(desktop_uv(&process), Some(existing));
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
        let process = ServerProcess::new();

        assert_eq!(
            start_server_inner(&process, port),
            Ok("already_running".to_string())
        );
        assert_eq!(get_stage(&process), "ready");
    }

    #[test]
    fn desktop_startup_rejects_incompatible_existing_backend() {
        let body = r#"{"ok":true,"status":"ok","version":"99.0.0","desktopCompatibility":{"contractVersion":"1.0.0","backendVersion":"99.0.0","versionPolicy":"exact-release"}}"#.to_string();
        let port = serve_health_once(body);
        let process = ServerProcess::new();

        let error =
            start_server_inner(&process, port).expect_err("incompatible backend must fail closed");
        assert!(error.contains("Incompatible service detected"));
        assert!(error.contains(env!("CARGO_PKG_VERSION")));
        assert!(error.contains(DESKTOP_API_CONTRACT_VERSION));
        assert!(error.contains("kicad-mcp-pro=="));
        assert_eq!(get_stage(&process), "failed");
    }

    #[test]
    fn owner_quiesce_uses_session_cookie_and_csrf() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            for (index, stream) in listener.incoming().take(2).enumerate() {
                let mut stream = stream.unwrap();
                let mut request = [0; 4096];
                let count = stream.read(&mut request).unwrap();
                let request = String::from_utf8_lossy(&request[..count]).to_ascii_lowercase();
                let body = if index == 0 {
                    assert!(request.starts_with("get /api/owner/session "));
                    r#"{"csrf_token":"test-csrf"}"#
                } else {
                    assert!(request.starts_with("post /api/maintenance/quiesce "));
                    assert!(request.contains("cookie: kicad_owner_session=test-session"));
                    assert!(request.contains("x-kicad-owner-csrf: test-csrf"));
                    assert!(request.contains("origin: http://127.0.0.1:"));
                    r#"{"ok":true,"state":"quiesced","token":"test-token"}"#
                };
                write!(stream, "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nSet-Cookie: kicad_owner_session=test-session; Path=/api\r\nConnection: close\r\n\r\n{}", body.len(), body).unwrap();
            }
        });
        let (_, _, _, token) = tauri::async_runtime::block_on(quiesce_backend(&base)).unwrap();
        assert_eq!(token, "test-token");
        server.join().unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn managed_backend_shutdown_reaps_its_owned_launcher() {
        let mut cmd = Command::new("cmd.exe");
        cmd.args(["/D", "/C", "ping -n 20 127.0.0.1 > NUL"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let mut owned = ManagedBackend::spawn(&mut cmd).expect("start test-owned backend launcher");
        owned.shutdown();
        assert!(owned.try_wait().expect("query stopped child").is_some());
    }

    #[test]
    fn desktop_server_process_cancel_changes_stage() {
        let process = ServerProcess::new();
        assert_eq!(get_stage(&process), "idle");
        set_stage(&process, "cancelled");
        assert_eq!(get_stage(&process), "cancelled");
    }
}
