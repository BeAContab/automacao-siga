from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.siga_extractor import BatchExtractionResult, SigaContributorExtractor
from src.extraction.spreadsheet import load_cgfs_from_xlsx
from src.live_assist import LiveAssistSession
from src.months import MONTH_OPTIONS
from src.utils.browser import BrowserSession, get_connect_browser_url, launch_debug_browser
from src.utils.logging_setup import configure_logging


def build_parser() -> argparse.ArgumentParser:
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
        help="Browser channel used by Playwright, for example msedge or chrome.",
    )
    parser.add_argument(
        "--connect-browser-url",
        help="Connect to an existing browser via CDP, for example http://127.0.0.1:9222.",
    )
    parser.add_argument(
        "--reset-browser-profile",
        action="store_true",
        help="Recreate the persistent browser profile before running the automation.",
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
        help="Path to the XLSX spreadsheet with the 'cgf' column. If omitted, the terminal will ask.",
    )
    parser.add_argument(
        "--month",
        choices=MONTH_OPTIONS,
        help="Reference month used by the extraction. If omitted, the terminal will ask.",
    )
    return parser


def _prompt_month() -> str:
    print("Meses disponiveis:")
    for index, month in enumerate(MONTH_OPTIONS, start=1):
        print(f"{index}. {month}")

    while True:
        value = input("Informe o mes de referencia (nome ou numero): ").strip()
        if value.isdigit():
            position = int(value)
            if 1 <= position <= len(MONTH_OPTIONS):
                return MONTH_OPTIONS[position - 1]
        for month in MONTH_OPTIONS:
            if month.lower() == value.lower():
                return month
        print("Mes invalido. Exemplo: Maio ou 5.")


def _prompt_spreadsheet() -> Path:
    default_path = Path("cgf.xlsx")
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


def _print_batch_summary(results: list[BatchExtractionResult], total_rows: int) -> None:
    download_count = sum(len(result.fiscal_results) for result in results)
    print("")
    print("Processo concluido.")
    print(f"Contribuintes processados: {len(results)} de {total_rows}")
    print(f"Detalhamentos baixados: {download_count}")
    if results:
        print(f"Pasta da ultima saida: {results[-1].taxpayer_folder}")
    for result in results:
        print(f"- {result.cgf}: {result.message}")


def run_interactive_terminal(settings: Settings, spreadsheet: str | None, month: str | None) -> int:
    month_reference = month or _prompt_month()
    spreadsheet_path = Path(spreadsheet).expanduser() if spreadsheet else _prompt_spreadsheet()
    spreadsheet_rows = load_cgfs_from_xlsx(spreadsheet_path)

    print(f"Mes de referencia: {month_reference}")
    print(f"Planilha: {spreadsheet_path}")
    print("Abrindo navegador para login manual...")
    # Forca o fluxo interativo a reutilizar o mesmo navegador via CDP.
    if not settings.connect_browser_url:
        settings.connect_browser_url = get_connect_browser_url(settings)
    launch_debug_browser(settings)

    flow = SigaLoginFlow(settings)
    extractor = SigaContributorExtractor(settings, allow_manual_login_prompt=False)

    with BrowserSession(settings) as context:
        page = context.pages[0] if context.pages else context.new_page()
        flow._open_siga(page)
        input("Faca o login manualmente no navegador aberto e pressione Enter para continuar...")
        authenticated_page = flow.confirm_authenticated_context(context, browser=context.browser)
        print(f"Login confirmado: {authenticated_page.title()}")

        results = extractor.run_batch_from_spreadsheet_in_context(
            context,
            spreadsheet_rows,
            month_reference,
        )

    _print_batch_summary(results, len(spreadsheet_rows))
    return 0


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    settings = Settings(
        headless=args.headless,
        browser_channel=args.browser_channel,
        connect_browser_url=args.connect_browser_url,
        manual_login_timeout_ms=args.manual_login_timeout * 1000,
        reset_browser_profile=args.reset_browser_profile,
    )
    configure_logging(settings.log_dir / "run.log")

    try:
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

        return run_interactive_terminal(settings, args.spreadsheet, args.month)
    except Exception:
        logging.exception("Unhandled fatal error during execution")
        return 1


if __name__ == "__main__":
    sys.exit(main())
