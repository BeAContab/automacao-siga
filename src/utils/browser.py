from __future__ import annotations

import logging
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from src.config import Settings


LOGGER = logging.getLogger(__name__)

WINDOWS_BROWSER_PATHS = {
    "chrome": (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ),
    "msedge": (
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ),
}


class BrowserLauncherError(RuntimeError):
    pass


def get_debug_browser_pid_path(settings: Settings) -> Path:
    return settings.browser_debug_profile_dir / "browser.pid"


def get_connect_browser_url(settings: Settings) -> str:
    if settings.connect_browser_url:
        return settings.connect_browser_url
    return f"http://127.0.0.1:{settings.remote_debugging_port}"


def is_cdp_available(url: str, timeout_seconds: int = 3) -> bool:
    version_url = f"{url.rstrip('/')}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=timeout_seconds) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def resolve_browser_executable(settings: Settings) -> Path:
    candidates = WINDOWS_BROWSER_PATHS.get(settings.browser_channel, ())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise BrowserLauncherError(
        f"Nao foi possivel localizar o executavel do navegador para o canal '{settings.browser_channel}'."
    )


def launch_debug_browser(settings: Settings) -> subprocess.Popen[str] | None:
    executable = resolve_browser_executable(settings)
    connect_url = get_connect_browser_url(settings)
    port = settings.remote_debugging_port

    if is_cdp_available(connect_url):
        LOGGER.info("A browser with CDP is already available at %s", connect_url)
        return None

    settings.browser_debug_profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={settings.browser_debug_profile_dir}",
        "--start-maximized",
        settings.siga_url,
    ]
    LOGGER.info("Launching browser with remote debugging: %s", executable)
    process = subprocess.Popen(command)
    get_debug_browser_pid_path(settings).write_text(str(process.pid), encoding="ascii")
    wait_for_cdp(settings)
    return process


def shutdown_debug_browser(settings: Settings) -> bool:
    connect_url = get_connect_browser_url(settings)
    pid_path = get_debug_browser_pid_path(settings)
    closed = False

    if is_cdp_available(connect_url):
        LOGGER.info("Closing browser via CDP at %s", connect_url)
        playwright = sync_playwright().start()
        browser = None
        try:
            browser = playwright.chromium.connect_over_cdp(connect_url)
            browser.close()
            closed = True
        except Exception:
            LOGGER.exception("Failed to close browser via CDP")
        finally:
            if browser is not None:
                with suppress(Exception):
                    browser.close()
            playwright.stop()

    if not closed and pid_path.exists():
        try:
            pid_value = int(pid_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            pid_value = 0

        if pid_value > 0:
            LOGGER.info("Closing browser process via taskkill for PID %s", pid_value)
            result = subprocess.run(
                ["taskkill", "/PID", str(pid_value), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            closed = result.returncode == 0
            if not closed:
                LOGGER.warning("taskkill did not confirm browser shutdown for PID %s", pid_value)

    with suppress(OSError):
        pid_path.unlink()

    deadline = time.time() + 5
    while time.time() < deadline:
        if not is_cdp_available(connect_url, timeout_seconds=1):
            return True
        time.sleep(0.25)

    return closed or not is_cdp_available(connect_url, timeout_seconds=1)


def wait_for_cdp(settings: Settings) -> None:
    connect_url = get_connect_browser_url(settings)
    deadline = time.time() + (settings.browser_start_timeout_ms / 1000)
    while time.time() < deadline:
        if is_cdp_available(connect_url):
            return
        time.sleep(0.5)
    raise BrowserLauncherError(
        f"Nao foi possivel conectar ao navegador em {connect_url}. "
        "Verifique se o navegador abriu corretamente com depuracao remota."
    )


class BrowserSession:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self._connected_over_cdp = False

    def __enter__(self) -> BrowserContext:
        self.settings.ensure_runtime_dirs()
        self._playwright = sync_playwright().start()

        if self.settings.connect_browser_url:
            connect_url = get_connect_browser_url(self.settings)
            LOGGER.info("Connecting to existing browser via CDP at %s", connect_url)
            if is_cdp_available(connect_url):
                self.browser = self._playwright.chromium.connect_over_cdp(connect_url)
                self._connected_over_cdp = True
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = self.browser.new_context()
                return self.context
            else:
                LOGGER.info("CDP not available at %s. Falling back to persistent launch.", connect_url)

        if self.settings.reset_browser_profile and self.settings.browser_profile_dir.exists():
            LOGGER.warning("Resetting browser profile at %s", self.settings.browser_profile_dir)
            shutil.rmtree(self.settings.browser_profile_dir, ignore_errors=True)
            self.settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)

        # Habilitamos depuracao remota no perfil persistente para permitir conexoes CDP futuras do Live Assist
        launch_args = [
            "--start-maximized",
            f"--remote-debugging-port={self.settings.remote_debugging_port}"
        ]
        self.context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.settings.browser_profile_dir),
            channel=self.settings.browser_channel,
            headless=self.settings.headless,
            slow_mo=self.settings.slow_mo_ms,
            accept_downloads=True,
            no_viewport=True,
            args=launch_args,
        )
        return self.context

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context is not None and not self._connected_over_cdp:
            self.context.close()
        if self.browser is not None and not self._connected_over_cdp:
            self.browser.close()
        if self._playwright is not None:
            self._playwright.stop()
