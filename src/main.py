from __future__ import annotations

"""Ponto de entrada da automação do SIGA.

Este módulo coordena a leitura dos argumentos e a abertura da interface gráfica
(a GUI é o único modo de extração suportado).
"""

import argparse
import logging
import os
import sys
from contextlib import suppress

from dotenv import load_dotenv

from src.config import Settings
from src.utils.certificate_policy import (
    ClientCertificate,
    clear_auto_certificate_selection,
    configure_auto_certificate_selection,
)
from src.utils.logging_setup import configure_logging
from src.utils.narration import configure_narration, narrate, narrate_error


def build_parser() -> argparse.ArgumentParser:
    """Define os argumentos aceitos ao abrir a GUI."""
    parser = argparse.ArgumentParser(
        description="SIGA automation (GUI mode)."
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser without UI.",
    )
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        help="Browser used by Selenium, for example msedge or chrome.",
    )
    parser.add_argument(
        "--connect-browser-url",
        help="Connect to an existing browser via CDP, for example http://127.0.0.1:9222.",
    )
    parser.add_argument(
        "--disable-attach",
        action="store_true",
        help="Disable the automatic attach to an existing authenticated SIGA tab.",
    )
    parser.add_argument(
        "--reset-browser-profile",
        action="store_true",
        help="Recreate the persistent browser profile before running the automation.",
    )
    parser.add_argument(
        "--force-restart-browser",
        action="store_true",
        help="Terminate browser processes for the selected channel before opening a new CDP session.",
    )
    parser.add_argument(
        "--isolated-browser-profile",
        action="store_true",
        help="Use the automation profile instead of an explicitly requested system Chrome profile.",
    )
    parser.add_argument(
        "--system-browser-profile",
        action="store_true",
        help="Try to use the normal Chrome user profile. This may block CDP in recent Chrome versions.",
    )
    parser.add_argument(
        "--chrome-profile-directory",
        help="Optional Chrome profile directory, for example Default or Profile 1.",
    )
    parser.add_argument(
        "--skip-certificate-policy",
        action="store_true",
        help="Do not configure Chrome/Edge certificate auto-selection policy before login.",
    )
    parser.add_argument(
        "--clear-certificate-policy",
        action="store_true",
        help="Remove the certificate auto-selection policy configured by this tool and exit.",
    )
    parser.add_argument(
        "--keep-certificate-policy",
        action="store_true",
        help=(
            "Do not remove the certificate auto-selection policy after this run finishes. "
            "By default the policy is cleared automatically once the run completes."
        ),
    )
    parser.add_argument(
        "--manual-login-timeout",
        type=int,
        default=300,
        help="Seconds to wait for the authenticated SIGA page after manual login confirmation.",
    )
    parser.add_argument(
        "--spreadsheet",
        help="Path to the XLSX spreadsheet with the 'cnpj' column, used to prefill the GUI.",
    )
    parser.add_argument(
        "--month",
        nargs="+",
        help="Reference month used to prefill the GUI (only the first value is used).",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Reference year used to prefill the GUI.",
    )
    return parser


def _read_env_bool(name: str, default: bool) -> bool:
    """Lê uma variável booleana do ambiente com formatos comuns do Windows e Unix."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "sim"}:
        return True
    if normalized in {"0", "false", "no", "off", "nao"}:
        return False
    return default


def _prompt_certificate_choice(certificates: list[ClientCertificate]) -> ClientCertificate | None:
    """Pede ao operador que escolha, entre vários certificados, qual usar para o login no SIGA."""
    # Sem terminal interativo não há como confirmar com segurança; pula a política.
    if not sys.stdin or not sys.stdin.isatty():
        print(
            "Vários certificados de autenticação foram encontrados, mas não há terminal interativo "
            "para escolher. A seleção automática de certificado não será configurada."
        )
        return None

    print("")
    print("Foram encontrados vários certificados de autenticação de cliente:")
    for index, certificate in enumerate(certificates, start=1):
        validade = f" (válido até {certificate.not_after})" if certificate.not_after else ""
        print(f"{index}. {certificate.subject_cn}{validade}")
    print("Pressione Enter sem digitar nada para não configurar a seleção automática.")

    while True:
        raw_value = input("Escolha o número do certificado a usar: ").strip()
        if not raw_value:
            return None
        if raw_value.isdigit():
            position = int(raw_value)
            if 1 <= position <= len(certificates):
                return certificates[position - 1]
        print(f"Opção inválida. Informe um número de 1 a {len(certificates)} ou Enter para cancelar.")


def run_gui_mode(
    settings: Settings,
    spreadsheet: str | None = None,
    month: str | None = None,
    year: int | None = None,
) -> int:
    """Abre a interface gráfica baseada em Tkinter e preserva valores iniciais vindos da linha de comando."""
    from src.gui import launch_gui

    initial_year = str(year) if year is not None else None
    return launch_gui(
        settings,
        initial_spreadsheet=spreadsheet,
        initial_month=month,
        initial_year=initial_year,
    )


def main() -> int:
    """Configura o ambiente e escolhe entre a GUI, o modo assistido ou a limpeza de política."""
    load_dotenv()
    args = build_parser().parse_args()
    settings = Settings(
        headless=args.headless,
        browser_channel=args.browser_channel,
        connect_browser_url=args.connect_browser_url,
        prefer_existing_siga_session=(
            _read_env_bool("PREFER_EXISTING_SIGA_SESSION", True) and not args.disable_attach
        ),
        manual_login_timeout_ms=args.manual_login_timeout * 1000,
        reset_browser_profile=args.reset_browser_profile,
        force_restart_browser=args.force_restart_browser,
        use_system_browser_profile=args.system_browser_profile and not args.isolated_browser_profile,
        chrome_profile_directory=args.chrome_profile_directory,
        configure_certificate_policy=not args.skip_certificate_policy,
        # nfce_cpf/nfce_senha (modo NFC-e) NÃO vêm daqui: são digitados na própria GUI
        # e ficam só em memória pelo tempo da execução — nunca persistidos em .env/disco.
    )
    configure_logging(settings.log_dir / "run.log")
    # A GUI nao tem um console util para o operador ler; a narracao ali chega pelo
    # console interno da GUI (ver SigaAutomationGUI.__init__), nao stdout.
    configure_narration(settings.log_dir, console=False)

    # Este modo apenas limpa a política de certificado e encerra.
    if args.clear_certificate_policy:
        removed = clear_auto_certificate_selection(settings)
        print(
            "Política de seleção automática de certificado removida."
            if removed
            else "Nenhuma política de seleção automática de certificado foi encontrada."
        )
        return 0

    certificate_policy_applied = False
    try:
        # A política de certificado é aplicada antes do navegador para reduzir atrito no login.
        if settings.configure_certificate_policy:
            certificate_policy = configure_auto_certificate_selection(
                settings, selector=_prompt_certificate_choice
            )
            certificate_policy_applied = certificate_policy.applied
            if certificate_policy.applied and certificate_policy.subject_cn:
                print(f"Certificado configurado para seleção automática: {certificate_policy.subject_cn}")
            elif certificate_policy.requires_manual_selection:
                print(
                    "A seleção automática de certificado não foi configurada. "
                    "O navegador exibirá o prompt padrão para você escolher o certificado no login."
                )
            elif certificate_policy.reg_file_path:
                print("Não foi possível gravar a política de certificado automaticamente.")
                print(f"Arquivo .reg gerado para aplicação manual: {certificate_policy.reg_file_path}")

        # A GUI é o único modo de extração suportado.
        return run_gui_mode(settings, args.spreadsheet, args.month[0] if args.month else None, args.year)
    except Exception as exc:
        logging.exception("Erro fatal não tratado durante a execução")
        narrate_error("Ocorreu um erro inesperado e a execução foi interrompida: %s", exc)
        return 1
    finally:
        # A política fica ativa no navegador do usuário mesmo fora da automação se não for
        # removida; por padrão a limpeza acontece ao final de toda execução (sucesso ou erro).
        if certificate_policy_applied and not args.keep_certificate_policy:
            with suppress(Exception):
                if clear_auto_certificate_selection(settings):
                    narrate("Política de seleção automática de certificado removida ao final da execução.")


if __name__ == "__main__":
    sys.exit(main())
