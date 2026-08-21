from __future__ import annotations

"""Configurações centrais e caminhos padrão usados em toda a automação."""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CERTIFICATE_DIR = PROJECT_ROOT / "certificado"
DEFAULT_BROWSER_PROFILE_DIR = PROJECT_ROOT / ".browser-profile"
DEFAULT_BROWSER_DEBUG_PROFILE_DIR = PROJECT_ROOT / "browser-debug-profile"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "saida"


@dataclass(slots=True)
class Settings:
    """Agrupa parâmetros de execução, diretórios e timeouts da automação."""
    siga_url: str = "https://siga.sefaz.ce.gov.br/ui/"
    browser_channel: str = "chrome"
    connect_browser_url: str | None = None
    prefer_existing_siga_session: bool = True
    headless: bool = False
    slow_mo_ms: int = 250
    timeout_ms: int = 30_000
    browser_profile_dir: Path = DEFAULT_BROWSER_PROFILE_DIR
    browser_debug_profile_dir: Path = DEFAULT_BROWSER_DEBUG_PROFILE_DIR
    log_dir: Path = DEFAULT_LOG_DIR
    screenshot_path: Path = DEFAULT_LOG_DIR / "siga-login-poc.png"
    certificate_dir: Path = DEFAULT_CERTIFICATE_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    download_poll_interval_ms: int = 1_000
    download_wait_timeout_ms: int = 90_000
    download_retry_count: int = 2
    download_retry_delay_ms: int = 2_000
    click_certificate_option: bool = False
    manual_login_timeout_ms: int = 300_000
    reset_browser_profile: bool = False
    force_restart_browser: bool = False
    use_system_browser_profile: bool = False
    chrome_profile_directory: str | None = None
    configure_certificate_policy: bool = True
    blank_page_retry_count: int = 2
    siga_app_root_selector: str = "app-root"
    remote_debugging_port: int = 9222
    browser_start_timeout_ms: int = 15_000

    # --- Modo NFC-e (item 8): portagem de importação/NFCE/codigo-fonte/xml nfce.py ---
    nfce_login_url: str = "https://servicos.sefaz.ce.gov.br/internet/acessoseguro/servicosenha/logarusuario/login.asp"
    nfce_empresas_url: str = "https://servicos.sefaz.ce.gov.br/internet/acessoSeguro/EMPRESASDOCPF/CWEB2010.ASP?SSE=104&Destino=MFe%2FRedirJavaMFe%2Easp"
    nfce_logout_url: str = "https://servicos.sefaz.ce.gov.br/internet/acessoSeguro/ServicoSenha/EncerrarSessao/cweb2005.asp"
    # Credenciais nunca hardcoded nem persistidas: a GUI as preenche em runtime a partir
    # do que o usuário digita na tela (src/gui.py, nfce_cpf_var/nfce_senha_var), só em
    # memória pelo tempo da execução — nunca gravadas em .env, planilha ou log.
    nfce_cpf: str | None = None
    nfce_senha: str | None = None
    # Sem default de rede (ex.: Y:\...) — selecionável pelo usuário, como qualquer planilha.
    nfce_base_spreadsheet_path: Path | None = None
    # Pasta com uma planilha de chaves de 44 dígitos por empresa (nome do arquivo
    # contendo o CNPJ), usada para resolver quais chaves buscar por empresa.
    nfce_keys_folder_path: Path | None = None
    nfce_session_renewal_seconds: int = 480
    nfce_session_renewal_check_every_n_keys: int = 40
    nfce_batch_max_keys: int = 300
    nfce_session_recovery_wait_seconds: int = 240

    # --- Modo NF-e (Meu DANFE): portagem de importação/NFE 2/automacao-meu-danfe/main.py ---
    # Site público de terceiros (consulta por chave de acesso, sem login/credenciais).
    nf_meudanfe_url: str = "https://meudanfe.com.br/"
    # Caminho opcional do chrome.exe; None deixa o undetected_chromedriver localizar sozinho.
    nf_meudanfe_chrome_path: Path | None = None
    # Pasta com as planilhas .xlsx contendo a coluna "Chave NF-e" (ex.: a própria pasta de
    # saída do modo SIGA, já que o detalhamento de NF-e do SIGA tem essa mesma coluna).
    nf_meudanfe_input_folder: Path | None = None
    # 1 a 4 instâncias de Chrome em paralelo (undetected_chromedriver, uma por worker);
    # limitado a 4 mesmo que o usuário configure mais, para reduzir risco de bloqueio anti-bot.
    nf_meudanfe_max_workers: int = 1
    nf_meudanfe_captcha_timeout_seconds: int = 180
    nf_meudanfe_download_timeout_seconds: int = 45

    def ensure_runtime_dirs(self) -> None:
        """Garante que os diretórios de runtime existam antes da execução começar."""
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.browser_debug_profile_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def find_a1_certificate(self) -> Path | None:
        """Procura um certificado A1 local para apoiar a seleção automática."""
        for pattern in ("*.pfx", "*.p12"):
            matches = sorted(self.certificate_dir.glob(pattern))
            if matches:
                return matches[0]
        return None
