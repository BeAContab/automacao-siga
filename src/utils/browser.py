from __future__ import annotations

"""Criação, reutilização e encerramento da sessão de navegador usada pela automação."""

import logging
import shutil
import subprocess
import time
import urllib.parse
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from src.config import Settings
from src.utils.selenium_compat import Browser, BrowserContext


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

BROWSER_IMAGE_NAMES = {
    "chrome": "chrome.exe",
    "msedge": "msedge.exe",
}


class BrowserLauncherError(RuntimeError):
    pass


def get_debug_browser_pid_path(settings: Settings) -> Path:
    """Retorna o arquivo que guarda o PID do navegador de depuração."""
    return settings.browser_debug_profile_dir / "browser.pid"


def get_connect_browser_url(settings: Settings) -> str:
    """Resolve a URL CDP que será usada para conectar ao navegador."""
    if settings.connect_browser_url:
        return settings.connect_browser_url
    return f"http://127.0.0.1:{settings.remote_debugging_port}"


def is_cdp_available(url: str, timeout_seconds: int = 3) -> bool:
    """Verifica se o navegador já está expondo a interface CDP esperada."""
    version_url = f"{url.rstrip('/')}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=timeout_seconds) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def resolve_browser_executable(settings: Settings) -> Path:
    """Localiza o executável do Chrome ou Edge de acordo com o canal escolhido."""
    candidates = WINDOWS_BROWSER_PATHS.get(settings.browser_channel, ())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise BrowserLauncherError(
        f"Nao foi possivel localizar o executavel do navegador para o canal '{settings.browser_channel}'."
    )


def launch_debug_browser(settings: Settings) -> subprocess.Popen[str] | None:
    """Sobe ou reaproveita um navegador com depuração remota ativa."""
    executable = resolve_browser_executable(settings)
    connect_url = get_connect_browser_url(settings)
    port = settings.remote_debugging_port

    if settings.force_restart_browser:
        terminate_browser_processes(settings)

    if is_cdp_available(connect_url):
        LOGGER.info("A browser with CDP is already available at %s", connect_url)
        return None

    try:
        return _start_debug_browser_process(settings, executable, port)
    except BrowserLauncherError:
        LOGGER.warning(
            "CDP did not become available on first attempt; forcing browser restart and trying once more."
        )
        terminate_browser_processes(settings)
        return _start_debug_browser_process(settings, executable, port)


def _start_debug_browser_process(settings: Settings, executable: Path, port: int) -> subprocess.Popen[str]:
    """Inicia o navegador com perfil controlado pela automação."""
    settings.browser_debug_profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        f"--remote-debugging-port={port}",
        "--start-maximized",
    ]
    # Quando o login depende do certificado do usuário, o perfil do sistema pode ser necessário.
    if settings.use_system_browser_profile:
        LOGGER.info("Launching browser with the system user profile for certificate selection")
        if settings.chrome_profile_directory:
            command.append(f"--profile-directory={settings.chrome_profile_directory}")
    else:
        command.append(f"--user-data-dir={settings.browser_debug_profile_dir}")
    command.append(settings.siga_url)
    LOGGER.info("Launching browser with remote debugging: %s", executable)
    process = subprocess.Popen(command)
    get_debug_browser_pid_path(settings).write_text(str(process.pid), encoding="ascii")
    wait_for_cdp(settings)
    return process


def terminate_browser_processes(settings: Settings) -> None:
    """Encerra processos do navegador para limpar sessões antigas antes de relançar."""
    image_name = BROWSER_IMAGE_NAMES.get(settings.browser_channel)
    if not image_name:
        LOGGER.warning("Skipping forced browser restart for unknown channel: %s", settings.browser_channel)
        return

    LOGGER.info("Forcing browser restart by terminating '%s' processes", image_name)
    result = subprocess.run(
        ["taskkill", "/IM", image_name, "/T", "/F"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        LOGGER.info("Terminated existing '%s' processes", image_name)
    else:
        LOGGER.info("No running '%s' process found or taskkill returned %s", image_name, result.returncode)

    with suppress(OSError):
        get_debug_browser_pid_path(settings).unlink()

    deadline = time.time() + 5
    connect_url = get_connect_browser_url(settings)
    while time.time() < deadline:
        if not is_cdp_available(connect_url, timeout_seconds=1):
            return
        time.sleep(0.25)


def shutdown_debug_browser(settings: Settings) -> bool:
    """Tenta fechar o navegador pela CDP e, se necessário, cai para PID explícito."""
    connect_url = get_connect_browser_url(settings)
    pid_path = get_debug_browser_pid_path(settings)
    closed = False

    if is_cdp_available(connect_url):
        LOGGER.info("Closing browser via Selenium debugger attach at %s", connect_url)
        driver = None
        try:
            driver = create_debugger_driver(settings, connect_url)
            driver.execute_cdp_cmd("Browser.close", {})
            closed = True
        except Exception:
            LOGGER.exception("Failed to close browser via CDP")
        finally:
            if driver is not None:
                with suppress(Exception):
                    driver.quit()

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
    """Aguarda até que a porta de depuração do navegador fique pronta para uso."""
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
    """Gerencia o ciclo de vida do WebDriver e do contexto compartilhado da automação."""
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self._connected_over_cdp = False

    def __enter__(self) -> BrowserContext:
        """Cria ou anexa o navegador e devolve o contexto pronto para navegação."""
        self.settings.ensure_runtime_dirs()

        if self.settings.connect_browser_url:
            connect_url = get_connect_browser_url(self.settings)
            LOGGER.info("Connecting to existing browser via Selenium debugger at %s", connect_url)
            if is_cdp_available(connect_url):
                self._connected_over_cdp = True
                driver = create_debugger_driver(self.settings, connect_url)
                self.context = BrowserContext(driver, self.settings, owns_driver=False)
                self.browser = Browser(driver, self.context)
                self.context.browser = self.browser
                return self.context
            else:
                LOGGER.info("Debugger not available at %s. Falling back to WebDriver launch.", connect_url)

        if self.settings.reset_browser_profile and self.settings.browser_profile_dir.exists():
            LOGGER.warning("Resetting browser profile at %s", self.settings.browser_profile_dir)
            shutil.rmtree(self.settings.browser_profile_dir, ignore_errors=True)
            self.settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)

        driver = create_webdriver(self.settings)
        self.context = BrowserContext(driver, self.settings, owns_driver=True)
        self.browser = Browser(driver, self.context)
        self.context.browser = self.browser
        return self.context

    def __exit__(self, exc_type, exc, tb) -> None:
        """Fecha o driver ou apenas a conexão, conforme a origem da sessão."""
        if self.context is not None:
            self.context.close()


def create_debugger_driver(settings: Settings, connect_url: str):
    """Cria um WebDriver conectado a uma sessão já aberta via CDP."""
    debugger_address = _debugger_address(connect_url)
    options = _build_browser_options(settings, debugger_address=debugger_address)
    return _create_driver(settings, options)


def create_webdriver(settings: Settings):
    """Cria um WebDriver novo quando não existe sessão reutilizável."""
    options = _build_browser_options(settings)
    return _create_driver(settings, options)


def _build_browser_options(settings: Settings, debugger_address: str | None = None):
    """Prepara as opções do navegador com base no modo de execução escolhido."""
    if settings.browser_channel == "msedge":
        options = webdriver.EdgeOptions()
    else:
        options = webdriver.ChromeOptions()

    if debugger_address:
        options.add_experimental_option("debuggerAddress", debugger_address)
        return options

    options.add_argument("--start-maximized")
    options.add_argument(f"--remote-debugging-port={settings.remote_debugging_port}")
    if settings.headless:
        options.add_argument("--headless=new")
    if settings.use_system_browser_profile:
        LOGGER.info("Launching WebDriver with the system user profile for certificate selection")
        if settings.chrome_profile_directory:
            options.add_argument(f"--profile-directory={settings.chrome_profile_directory}")
    else:
        options.add_argument(f"--user-data-dir={settings.browser_profile_dir}")

    download_dir = settings.output_dir / "_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    return options


def _create_driver(settings: Settings, options):
    """Instancia o driver do Selenium e traduz falhas em uma exceção mais amigável."""
    try:
        if settings.browser_channel == "msedge":
            return webdriver.Edge(options=options)
        return webdriver.Chrome(options=options)
    except WebDriverException as exc:
        raise BrowserLauncherError(
            "Nao foi possivel iniciar/conectar o Selenium WebDriver. "
            "Verifique se o navegador selecionado esta instalado e se o Selenium Manager consegue localizar o driver."
        ) from exc


def _debugger_address(connect_url: str) -> str:
    """Converte a URL CDP no formato aceito pela opção `debuggerAddress`."""
    parsed = urllib.parse.urlparse(connect_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    return f"{host}:{port}"
