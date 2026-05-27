from __future__ import annotations

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
    download_wait_timeout_ms: int = 60_000
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

    def ensure_runtime_dirs(self) -> None:
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.browser_debug_profile_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def find_a1_certificate(self) -> Path | None:
        for pattern in ("*.pfx", "*.p12"):
            matches = sorted(self.certificate_dir.glob(pattern))
            if matches:
                return matches[0]
        return None
