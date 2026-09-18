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

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeWebDriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.webdriver import WebDriver as EdgeWebDriver

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

    # Instalacoes fora do Program Files (ex.: por usuario, em %LocalAppData%) nao aparecem
    # nos caminhos fixos; shutil.which cobre esses casos ao consultar o PATH do sistema.
    image_name = BROWSER_IMAGE_NAMES.get(settings.browser_channel)
    if image_name:
        found = shutil.which(image_name)
        if found:
            return Path(found)

    raise BrowserLauncherError(
        f"Nao foi possivel localizar o executavel do navegador para o canal '{settings.browser_channel}'."
    )


def launch_debug_browser(settings: Settings, initial_url: str | None = None) -> subprocess.Popen[str] | None:
    """Sobe ou reaproveita um navegador com depuração remota ativa.

    `initial_url` é a página aberta na aba inicial (padrão: `settings.siga_url`, para o
    login manual do modo SIGA). O modo NFC-e passa `settings.nfce_login_url`, já que o
    login ali é automático e não faz sentido abrir a tela do SIGA.
    """
    executable = resolve_browser_executable(settings)
    connect_url = get_connect_browser_url(settings)
    port = settings.remote_debugging_port

    if settings.force_restart_browser:
        terminate_browser_processes(settings)

    if is_cdp_available(connect_url):
        LOGGER.info("Já existe um navegador com CDP disponível em %s", connect_url)
        return None

    try:
        return _start_debug_browser_process(settings, executable, port, initial_url)
    except BrowserLauncherError:
        LOGGER.warning(
            "O CDP nao ficou disponivel na primeira tentativa; reiniciando o navegador e tentando novamente."
        )
        terminate_browser_processes(settings)
        return _start_debug_browser_process(settings, executable, port, initial_url)


def _start_debug_browser_process(
    settings: Settings, executable: Path, port: int, initial_url: str | None = None
) -> subprocess.Popen[str]:
    """Inicia o navegador com perfil controlado pela automação."""
    settings.browser_debug_profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        f"--remote-debugging-port={port}",
        "--start-maximized",
        # O modo NFC-e abre cada empresa via `window.open()` disparado por script (não
        # por um clique real do usuário), e o Chrome bloqueia esse tipo de pop-up por
        # padrão — sem isso, a aba da empresa nunca chega a abrir.
        "--disable-popup-blocking",
        # O portal do NFC-e (servicos.sefaz.ce.gov.br) dispara a tela nativa "sua conexão
        # não é particular" por problema de cadeia de certificado do lado do governo —
        # sem essas flags, a automação trava esperando um clique manual em "Avançar".
        # Escopo isolado ao perfil dedicado da automação (browser_debug_profile_dir),
        # nunca ao Chrome pessoal do usuário.
        "--ignore-certificate-errors",
        "--allow-insecure-localhost",
    ]
    # Quando o login depende do certificado do usuário, o perfil do sistema pode ser necessário.
    if settings.use_system_browser_profile:
        LOGGER.info("Abrindo o navegador com o perfil do usuário do sistema para seleção de certificado")
        if settings.chrome_profile_directory:
            command.append(f"--profile-directory={settings.chrome_profile_directory}")
    else:
        command.append(f"--user-data-dir={settings.browser_debug_profile_dir}")
    command.append(initial_url or settings.siga_url)
    LOGGER.info("Abrindo o navegador com depuracao remota: %s", executable)
    process = subprocess.Popen(command)
    get_debug_browser_pid_path(settings).write_text(str(process.pid), encoding="ascii")
    wait_for_cdp(settings)
    return process


def _find_automation_browser_pids(settings: Settings, image_name: str) -> list[int]:
    """Localiza apenas os PIDs do navegador iniciados com o perfil de depuração da automação."""
    profile_marker = str(settings.browser_debug_profile_dir).replace("'", "''")
    script = (
        f"Get-CimInstance Win32_Process -Filter \"Name='{image_name}'\" | "
        f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{profile_marker}') }} | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        LOGGER.warning("Nao foi possivel consultar os processos do navegador via PowerShell")
        return []

    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _wait_for_pids_to_exit(pids: list[int], timeout_seconds: float = 5.0) -> bool:
    """Aguarda que todos os PIDs informados terminem, verificando via PowerShell.

    Complementa a verificação de CDP já existente: um processo zumbi pode ter fechado
    o listener mas ainda existir como processo no SO.
    Retorna True se todos os processos saíram dentro do timeout, False caso contrário.
    """
    if not pids:
        return True

    # Constrói um filtro PowerShell para verificar se algum dos PIDs ainda existe
    pids_filter = ", ".join(str(p) for p in pids)
    script = (
        f"$pids = @({pids_filter}); "
        "$alive = $pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }; "
        "$alive.Count"
    )
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            alive_count_str = result.stdout.strip()
            if alive_count_str.isdigit() and int(alive_count_str) == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            break
        time.sleep(0.5)
    return False


def terminate_browser_processes(settings: Settings) -> None:
    """Encerra apenas os processos do navegador iniciados pela automação, sem afetar janelas pessoais do usuário."""
    image_name = BROWSER_IMAGE_NAMES.get(settings.browser_channel)
    if not image_name:
        LOGGER.warning("Ignorando reinicio forcado do navegador para canal desconhecido: %s", settings.browser_channel)
        return

    if settings.use_system_browser_profile:
        # Nao e seguro distinguir processos da automacao de janelas pessoais do usuario
        # quando o perfil do sistema esta em uso; evita encerrar sessoes nao relacionadas.
        LOGGER.warning(
            "Reinicio forcado do navegador ignorado: o perfil do sistema esta em uso e nao e "
            "possivel identificar com seguranca apenas os processos da automacao."
        )
        return

    pids = _find_automation_browser_pids(settings, image_name)
    if not pids:
        LOGGER.info("Nenhum processo '%s' da automacao foi encontrado para encerrar", image_name)
        with suppress(OSError):
            get_debug_browser_pid_path(settings).unlink()
        return

    LOGGER.info("Forcando reinicio do navegador encerrando processos '%s' da automacao: %s", image_name, pids)
    kill_args = ["taskkill"]
    for pid in pids:
        kill_args += ["/PID", str(pid)]
    kill_args += ["/T", "/F"]
    result = subprocess.run(kill_args, capture_output=True, text=True, check=False)

    if result.returncode == 0:
        LOGGER.info("Processos '%s' da automacao encerrados", image_name)
    else:
        LOGGER.info("O taskkill para os processos da automacao retornou %s", result.returncode)

    with suppress(OSError):
        get_debug_browser_pid_path(settings).unlink()

    # Verificação dupla: aguarda tanto o fechamento da porta CDP quanto o término real dos PIDs.
    if not _wait_for_pids_to_exit(pids):
        LOGGER.warning(
            "Processos '%s' da automacao (PIDs: %s) ainda existem apos o taskkill. "
            "O encerramento pode não ter sido completo.",
            image_name,
            pids,
        )

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
        LOGGER.info("Fechando o navegador via conexao do Selenium debugger em %s", connect_url)
        driver = None
        try:
            driver = create_debugger_driver(settings, connect_url)
            driver.execute_cdp_cmd("Browser.close", {})
            closed = True
        except Exception:
            LOGGER.exception("Falha ao fechar o navegador via CDP")
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
            LOGGER.info("Fechando o processo do navegador via taskkill para o PID %s", pid_value)
            result = subprocess.run(
                ["taskkill", "/PID", str(pid_value), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            closed = result.returncode == 0
            if not closed:
                LOGGER.warning("O taskkill nao confirmou o encerramento do navegador para o PID %s", pid_value)
            else:
                # Verificacao por PID alem da porta CDP (ver PLANO_CORRECOES.md item 24)
                if not _wait_for_pids_to_exit([pid_value]):
                    LOGGER.warning(
                        "Processo do navegador (PID %s) ainda existe apos o taskkill. "
                        "O encerramento pode nao ter sido completo.",
                        pid_value,
                    )

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
        driver = None
        try:
            if self.settings.connect_browser_url:
                connect_url = get_connect_browser_url(self.settings)
                LOGGER.info("Conectando ao navegador existente via Selenium debugger em %s", connect_url)
                if is_cdp_available(connect_url):
                    self._connected_over_cdp = True
                    driver = create_debugger_driver(self.settings, connect_url)
                    self.context = BrowserContext(driver, self.settings, owns_driver=False)
                    self.browser = Browser(driver, self.context)
                    self.context.browser = self.browser
                    return self.context
                else:
                    LOGGER.info("Debugger indisponivel em %s. Usando a abertura via WebDriver.", connect_url)

            if self.settings.reset_browser_profile and self.settings.browser_profile_dir.exists():
                LOGGER.warning("Redefinindo o perfil do navegador em %s", self.settings.browser_profile_dir)
                shutil.rmtree(self.settings.browser_profile_dir, ignore_errors=True)
                self.settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)

            driver = create_webdriver(self.settings)
            self.context = BrowserContext(driver, self.settings, owns_driver=True)
            self.browser = Browser(driver, self.context)
            self.context.browser = self.browser
            return self.context
        except Exception:
            # Uma falha apos o driver ja ter sido criado nao aciona __exit__ (o protocolo de
            # context manager so chama __exit__ se __enter__ retornar); fecha explicitamente
            # para nao deixar o processo do navegador/driver orfao.
            if self.context is not None:
                with suppress(Exception):
                    self.context.close()
            elif driver is not None:
                with suppress(Exception):
                    driver.quit()
            raise

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
        # Importacao direta reduz falhas em empacotamentos com imports dinamicos.
        options = EdgeOptions()
    else:
        # Mantemos o acesso explicito ao Chrome para preservar compatibilidade.
        options = ChromeOptions()

    if debugger_address:
        options.add_experimental_option("debuggerAddress", debugger_address)
        return options

    options.add_argument("--start-maximized")
    options.add_argument(f"--remote-debugging-port={settings.remote_debugging_port}")
    # Mesmo motivo da flag em `_start_debug_browser_process`: o portal do NFC-e dispara a
    # tela nativa "sua conexão não é particular" por problema de certificado do lado do
    # governo. Esse caminho (via Selenium puro, não subprocess.Popen) é o usado quando o
    # `BrowserSession` não consegue anexar a um navegador já aberto via CDP -- ex.: a etapa
    # NFC-e da Cadeia Completa, que roda depois do navegador da etapa SIGA já ter sido
    # encerrado de propósito (ver `terminate_browser_processes` em `chain_extractor.py`).
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-insecure-localhost")
    if settings.headless:
        options.add_argument("--headless=new")
    if settings.use_system_browser_profile:
        LOGGER.info("Abrindo o WebDriver com o perfil do usuario do sistema para selecao de certificado")
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
            return EdgeWebDriver(options=options)
        return ChromeWebDriver(options=options)
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
