"""Windows desktop splash acceptance with a simulated incompatible local service.

The browser shim models native command returns. It never changes a real
backend, opens sponsor URLs, grants Cloud permissions, or modifies KiCad.
"""

from __future__ import annotations

import functools
import os
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get("E2E"), reason="Requires E2E=1"),
]

_FRONTEND = Path(__file__).resolve().parents[2] / "src-tauri" / "frontend"

_NATIVE_SHIM = """
(() => {
  const state = {port:3334, mode:'incompatible', attempted:[], external:[]};
  window.__desktopTest = state;
  window.__TAURI_INTERNALS__ = {invoke: async (command, args) => {
    if (command === 'server_status') {
      return state.mode === 'incompatible'
        ? {running:false, message:
            'Incompatible service detected at 127.0.0.1:3334/api/health: wrong version'}
        : {running:true, message:'Server is running.'};
    }
    if (command === 'desktop_readiness') {
      return state.mode === 'incompatible'
        ? {ready:false, incompatible:true, detail:'backend 4.7.0',
           port:3334, expectedVersion:'4.9.0'}
        : {ready:true, incompatible:false, detail:'verified',
           port:3335, expectedVersion:'4.9.0'};
    }
    if (command === 'desktop_backend_command') {
      return 'uv tool run --from kicad-mcp-pro==4.9.0 kicad-mcp-pro dashboard '
        + '--host 127.0.0.1 --port ' + state.port;
    }
    if (command === 'restart_server') {
      state.attempted.push(args.port);
      if (args.port !== 3335) throw Error('wrong requested port');
      state.port=3335;
      state.mode='ready';
      return 'started';
    }
    if (command === 'open_external_link') {
      state.external.push(args.url);
      return null;
    }
    throw Error('unexpected desktop command ' + command);
  }};
})();
"""


@pytest.fixture(scope="module")
def splash_origin() -> Iterator[str]:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(_FRONTEND))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_old_backend_has_one_click_isolated_desktop_recovery(
    page: Page, splash_origin: str
) -> None:
    """Old 3334 is not reused/stopped; the user picks 3335 and exact version."""
    page.add_init_script(_NATIVE_SHIM)
    page.route(
        "http://127.0.0.1:3335/ui?desktop=1",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<main><h1>Exact backend on 3335</h1></main>",
        ),
    )
    page.goto(splash_origin + "/index.html")
    separate = page.locator("#useSeparatePort")
    separate.wait_for(state="visible", timeout=12000)
    assert "Older or incompatible local backend" in page.locator("#status").inner_text()
    assert (
        page.locator("#cliCommand")
        .inner_text()
        .startswith("uv tool run --from kicad-mcp-pro==4.9.0")
    )
    assert page.locator("#cliCommand").inner_text().endswith("--port 3334")

    separate.click()
    page.wait_for_function("() => window.__desktopTest?.attempted.includes(3335)")
    assert page.locator("#cliCommand").inner_text().endswith("--port 3335")
    assert page.locator("#openLocalDashboard").get_attribute("href") == ("http://127.0.0.1:3335/ui")
    page.wait_for_url("http://127.0.0.1:3335/ui?desktop=1", timeout=10000)
    assert page.get_by_text("Exact backend on 3335").is_visible()


def test_sponsor_link_uses_native_allowlisted_command(page: Page, splash_origin: str) -> None:
    """A native splash link uses OS-browser bridge, not a WebView navigation."""
    page.add_init_script(_NATIVE_SHIM)
    page.goto(splash_origin + "/index.html")
    page.locator("#useSeparatePort").wait_for(state="visible", timeout=12000)
    page.locator('a.support-link[href="https://github.com/sponsors/oaslananka"]').click()
    assert page.evaluate("window.__desktopTest.external") == [
        "https://github.com/sponsors/oaslananka"
    ]
    assert page.url == splash_origin + "/index.html"


def test_second_port_failure_never_touches_existing_service(page: Page, splash_origin: str) -> None:
    """A busy 3335 is a visible failure, not a reason to kill 3334."""
    shim = _NATIVE_SHIM.replace(
        "state.port=3335;\n      state.mode='ready';\n      return 'started';",
        "state.port=3335; throw Error('alternate port is busy');",
    )
    assert shim != _NATIVE_SHIM
    page.add_init_script(shim)
    page.goto(splash_origin + "/index.html")
    page.locator("#useSeparatePort").wait_for(state="visible", timeout=12000)
    page.locator("#useSeparatePort").click()
    page.get_by_text("Could not start a separate backend", exact=False).wait_for()
    assert page.evaluate("window.__desktopTest.attempted") == [3335]
    assert page.evaluate("window.__desktopTest.mode") == "incompatible"
    assert page.locator("#cliCommand").inner_text().endswith("--port 3334") is False
    assert page.url == splash_origin + "/index.html"
