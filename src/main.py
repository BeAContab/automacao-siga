from __future__ import annotations

"""Ponto de entrada da automação do SIGA.

Este módulo coordena a leitura dos argumentos, o fluxo interativo do terminal
e a execução da extração com a sessão autenticada do navegador.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.siga_extractor import BatchExtractionResult, SigaContributorExtractor
from src.extraction.spreadsheet import load_cnpjs_from_xlsx
from src.live_assist import LiveAssistSession
from src.months import MONTH_OPTIONS
from src.utils.browser import BrowserSession, get_connect_browser_url, launch_debug_browser
from src.utils.certificate_policy import (
    clear_auto_certificate_selection,
    configure_auto_certificate_selection,
)
from src.utils.logging_setup import configure_logging

DOCUMENT_TAB_OPTIONS = ("NF-e", "NFC-e", "CT-e")


def build_parser() -> argparse.ArgumentParser:
    """Define os argumentos aceitos pela interface de terminal."""
    parser = argparse.ArgumentParser(
        description="SIGA automation with interactive terminal workflow."
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
        "--manual-login-timeout",
        type=int,
        default=300,
        help="Seconds to wait for the authenticated SIGA page after manual login confirmation.",
    )
    parser.add_argument(
        "--live-assist",
        action="store_true",
        help="Open SIGA for manual login and keep the browser session ready for assisted commands.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the graphical interface to select CNPJs and document tabs.",
    )
    parser.add_argument(
        "--live-command",
        help=(
            "Execute a live assisted browser command. Supported values: click-text, click-selector, "
            "click-label, fill-selector, fill-label, press, wait-text, click-coordinates, "
            "screenshot, download-table, open-month-if-positive, "
            "request-positive-details, close-browser, show-url, list-pages."
        ),
    )
    parser.add_argument(
        "--target",
        help="Target used by the live command, such as text, selector, label, coordinates or key.",
    )
    parser.add_argument(
        "--value",
        help="Optional value used by live fill commands.",
    )
    parser.add_argument(
        "--spreadsheet",
        help="Path to the XLSX spreadsheet with the 'cnpj' column. If omitted, the terminal will ask.",
    )
    parser.add_argument(
        "--month",
        nargs="+",
        help=(
            "Reference month(s) used by the extraction. "
            "Accepted values: month names (e.g. Maio Junho) or indexes in interactive mode."
        ),
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Reference year used by detail naming. If omitted, the terminal will ask.",
    )
    parser.add_argument(
        "--docs",
        nargs="+",
        help=(
            "Document tabs to process. Accepted values: NF-e, NFC-e, CT-e. "
            "You can provide one or more values, for example: --docs NF-e CT-e"
        ),
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


def _normalize_selected_months(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """Converte nomes ou índices de meses para a forma canônica usada internamente."""
    if not values:
        return []

    month_by_name = {month.casefold(): month for month in MONTH_OPTIONS}
    selected: list[str] = []
    for value in values:
        token = str(value).strip()
        if not token:
            continue
        if token.isdigit():
            position = int(token)
            if not (1 <= position <= len(MONTH_OPTIONS)):
                raise ValueError("Mes invalido. Use nomes de meses validos ou numeros de 1 a 12.")
            month_name = MONTH_OPTIONS[position - 1]
        else:
            month_name = month_by_name.get(token.casefold())
            if not month_name:
                raise ValueError("Mes invalido. Use nomes de meses validos ou numeros de 1 a 12.")
        if month_name not in selected:
            selected.append(month_name)
    return selected


def _prompt_months() -> list[str]:
    """Pergunta ao usuário quais meses devem entrar no lote de extração."""
    print("Meses disponiveis:")
    for index, month in enumerate(MONTH_OPTIONS, start=1):
        print(f"{index}. {month}")
    print("Exemplo: 5 ou Maio ou 5,6,7")

    while True:
        raw_value = input("Informe o(s) mes(es) de referencia [padrao: mes atual]: ").strip()
        if not raw_value:
            current_month = MONTH_OPTIONS[max(0, min(11, time.localtime().tm_mon - 1))]
            return [current_month]
        tokens = [token.strip() for token in raw_value.replace(";", ",").split(",") if token.strip()]
        try:
            months = _normalize_selected_months(tokens)
        except ValueError:
            print("Mes invalido. Exemplo: Maio ou 5,6.")
            continue
        if months:
            return months
        print("Mes invalido. Exemplo: Maio ou 5,6.")


def _prompt_year() -> str:
    """Pergunta o ano de referência com base no ano atual como padrão."""
    default_year = str(time.localtime().tm_year)
    while True:
        value = input(f"Informe o ano de referencia [padrao: {default_year}]: ").strip()
        if not value:
            return default_year
        if value.isdigit() and len(value) == 4:
            return value
        print("Ano invalido. Exemplo: 2026.")


def _prompt_spreadsheet() -> Path:
    """Solicita a planilha XLSX com a coluna `cnpj`."""
    default_path = Path("cnpj.xlsx")
    prompt = "Informe o caminho da planilha XLSX"
    if default_path.exists():
        prompt += f" [padrao: {default_path}]"
    prompt += ": "

    while True:
        raw_value = input(prompt).strip().strip('"')
        path = Path(raw_value) if raw_value else default_path
        if path.exists() and path.suffix.lower() == ".xlsx":
            return path
        print(f"Planilha invalida ou nao encontrada: {path}")


def _normalize_selected_tabs(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normaliza a escolha das abas fiscais e aceita aliases como `Todos`."""
    if not values:
        return list(DOCUMENT_TAB_OPTIONS)

    normalized_map = {value.casefold(): value for value in DOCUMENT_TAB_OPTIONS}
    selected: list[str] = []
    for value in values:
        normalized = str(value).strip().casefold()
        if normalized in {"todos", "todas", "all", "*"}:
            return list(DOCUMENT_TAB_OPTIONS)
        match = normalized_map.get(normalized)
        if not match:
            raise ValueError(
                "Valor invalido em --docs. Use apenas: NF-e, NFC-e, CT-e (ou 'all')."
            )
        if match not in selected:
            selected.append(match)
    return selected


def _prompt_document_tabs() -> list[str]:
    """Pergunta ao usuário quais documentos fiscais ele quer processar."""
    print("Quais documentos deseja processar?")
    print("1. NF-e")
    print("2. NFC-e")
    print("3. CT-e")
    print("4. Todos")
    print("Exemplo: 1,3 ou NF-e,CT-e")

    while True:
        raw_value = input("Informe as opcoes [padrao: Todos]: ").strip()
        if not raw_value:
            return list(DOCUMENT_TAB_OPTIONS)

        tokens = [token.strip() for token in raw_value.replace(";", ",").split(",") if token.strip()]
        expanded: list[str] = []
        for token in tokens:
            if token.isdigit():
                mapping = {"1": "NF-e", "2": "NFC-e", "3": "CT-e", "4": "all"}
                mapped = mapping.get(token)
                if not mapped:
                    expanded = []
                    break
                expanded.append(mapped)
            else:
                expanded.append(token)
        if not expanded:
            print("Opcao invalida. Exemplo: 1,2 ou NF-e,CT-e.")
            continue
        try:
            return _normalize_selected_tabs(expanded)
        except ValueError:
            print("Opcao invalida. Use NF-e, NFC-e, CT-e ou Todos.")


def _print_batch_summary(results: list[BatchExtractionResult], total_rows: int) -> None:
    """Mostra um resumo compacto do lote ao final da execução."""
    download_count = sum(len(result.fiscal_results) for result in results)
    print("")
    print("Processo concluido.")
    print(f"Contribuintes processados: {len(results)} de {total_rows}")
    print(f"Detalhamentos baixados: {download_count}")
    if results:
        print(f"Pasta da ultima saida: {results[-1].taxpayer_folder}")
    for result in results:
        print(f"- {result.cnpj}: {result.message}")


def run_interactive_terminal(
    settings: Settings,
    spreadsheet: str | None,
    months: list[str] | None,
    year: int | None,
    docs: list[str] | None,
) -> int:
    """Executa o fluxo interativo completo do terminal."""
    month_references = months if months else _prompt_months()
    reference_year = str(year) if year is not None else _prompt_year()
    selected_tabs = _normalize_selected_tabs(docs) if docs is not None else _prompt_document_tabs()
    spreadsheet_path = Path(spreadsheet).expanduser() if spreadsheet else _prompt_spreadsheet()
    spreadsheet_rows = load_cnpjs_from_xlsx(spreadsheet_path)

    print(f"Mes(es) de referencia: {', '.join(month_references)}")
    print(f"Ano de referencia: {reference_year}")
    print(f"Documentos selecionados: {', '.join(selected_tabs)}")
    print(f"Planilha: {spreadsheet_path}")
    # O navegador é aberto antes da extração para que o usuário conclua o login manual.
    print("Abrindo navegador para login manual...")
    if not settings.connect_browser_url:
        settings.connect_browser_url = get_connect_browser_url(settings)
    launch_debug_browser(settings)
    print("Conclua o login manual no navegador aberto.")
    print("Se a sessao ja estiver autenticada, apenas pressione Enter.")
    input("Pressione Enter somente depois que o SIGA estiver aberto/autenticado...")

    flow = SigaLoginFlow(settings)
    extractor = SigaContributorExtractor(settings, allow_manual_login_prompt=False)

    with BrowserSession(settings) as context:
        authenticated_page = flow.confirm_authenticated_context(context, browser=context.browser)
        print(f"Login confirmado: {authenticated_page.title()}")

        results: list[BatchExtractionResult] = []
        # Cada mês é processado separadamente para manter os nomes de saída previsíveis.
        for month_reference in month_references:
            print(f"Executando extracao para o mes: {month_reference}")
            results.extend(
                extractor.run_batch_from_spreadsheet_in_context(
                    context,
                    spreadsheet_rows,
                    month_reference,
                    reference_year,
                    selected_tabs,
                )
            )

    _print_batch_summary(results, len(spreadsheet_rows))
    return 0


def run_gui_mode(
    settings: Settings,
    spreadsheet: str | None = None,
    month: str | None = None,
    year: int | None = None,
) -> int:
    """Abre a interface gráfica e preserva valores iniciais vindos do CLI."""
    from src.gui import launch_gui

    initial_year = str(year) if year is not None else None
    return launch_gui(
        settings,
        initial_spreadsheet=spreadsheet,
        initial_month=month,
        initial_year=initial_year,
    )


def main() -> int:
    """Configura o ambiente e escolhe entre os modos interativo, assistido ou de limpeza."""
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
    )
    configure_logging(settings.log_dir / "run.log")

    try:
        # Este modo apenas limpa a política de certificado e encerra.
        if args.clear_certificate_policy:
            removed = clear_auto_certificate_selection(settings)
            print(
                "Politica de selecao automatica de certificado removida."
                if removed
                else "Nenhuma politica de selecao automatica de certificado foi encontrada."
            )
            return 0

        # A política de certificado é aplicada antes do navegador para reduzir atrito no login.
        if settings.configure_certificate_policy:
            certificate_policy = configure_auto_certificate_selection(settings)
            if certificate_policy.applied and certificate_policy.subject_cn:
                print(f"Certificado configurado para selecao automatica: {certificate_policy.subject_cn}")
            elif certificate_policy.reg_file_path:
                print("Nao foi possivel gravar a politica de certificado automaticamente.")
                print(f"Arquivo .reg gerado para aplicacao manual: {certificate_policy.reg_file_path}")

        # O modo assistido reaproveita a infraestrutura de navegador, mas deixa a ação manual guiada.
        if args.live_assist or args.live_command:
            session = LiveAssistSession(settings)
            if args.live_assist:
                result = session.start()
                logging.info("Live assist ready at %s", result.final_url)
                print("Sessao assistida pronta.")
                print(f"Pagina atual: {result.page_title}")
                print(f"URL atual: {result.final_url}")
                print("Envie o proximo passo no chat e eu executo conectando no mesmo navegador.")
                return 0

            result = session.execute_command(args.live_command, target=args.target, value=args.value)
            logging.info("Live command executed: %s", result.description)
            print(result.description)
            print(f"Pagina atual: {result.page_title}")
            print(f"URL atual: {result.current_url}")
            return 0

        if args.gui:
            return run_gui_mode(settings, args.spreadsheet, args.month[0] if args.month else None, args.year)

        parsed_docs = _normalize_selected_tabs(args.docs) if args.docs else None
        parsed_months = _normalize_selected_months(args.month) if args.month else None
        return run_interactive_terminal(settings, args.spreadsheet, parsed_months, args.year, parsed_docs)
    except Exception:
        logging.exception("Unhandled fatal error during execution")
        return 1


if __name__ == "__main__":
    sys.exit(main())
