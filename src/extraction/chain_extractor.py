from __future__ import annotations

"""Orquestra a cadeia completa SIGA -> NF-e (Meu DANFE) -> NFC-e numa unica execucao.

Reaproveita os tres extratores existentes (`SigaContributorExtractor`,
`MeudanfeBatchExtractor`, `NfceBatchExtractor`) sem alterar nenhum deles. A pasta de
saida do SIGA (padrao "COD - EMPRESA - CNPJ" por contribuinte) e usada diretamente
como entrada das duas etapas seguintes, porque ambas ja reconhecem essa convencao:

- `MeudanfeBatchExtractor.input_folder` varre recursivamente (`rglob`) por qualquer
  planilha com "nf-e" no nome, que e exatamente o que o SIGA grava por contribuinte/mes.
- `NfceBatchExtractor.keys_folder` ja resolve subpastas por CNPJ com essa mesma
  convencao (ver `_company_folder_for_cnpj` em nfce_extractor.py).

Se a etapa SIGA terminar com falhas parciais (CNPJ nao encontrado, download que
falhou), a cadeia segue para NF-e e NFC-e mesmo assim, processando o que foi baixado -
so um cancelamento explicito do usuario interrompe a cadeia entre etapas.
"""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.meudanfe_extractor import MeudanfeBatchExtractor, MeudanfeBatchResult
from src.extraction.nfce_extractor import NfceBatchExtractor, NfceBatchResult
from src.extraction.siga_extractor import BatchExtractionResult, SigaContributorExtractor
from src.extraction.spreadsheet import SpreadsheetRow
from src.utils.browser import BrowserSession, terminate_browser_processes
from src.utils.narration import narrate, narrate_success, narrate_warning

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ChainExtractionResult:
    """Resultado consolidado das tres etapas da cadeia."""

    siga_results: list[BatchExtractionResult] = field(default_factory=list)
    nfe_results: list[MeudanfeBatchResult] = field(default_factory=list)
    nfce_results: list[NfceBatchResult] = field(default_factory=list)


class ChainBatchExtractor:
    """Executa SIGA, depois NF-e, depois NFC-e, encadeando a saida do SIGA como
    entrada das duas etapas seguintes."""

    def __init__(
        self,
        settings: Settings,
        siga_output_dir: Path,
        nfe_output_dir: Path,
        nfce_output_dir: Path,
        nfce_base_spreadsheet_path: Path | None,
        nfe_max_workers: int,
    ) -> None:
        self.settings = settings
        self.siga_output_dir = siga_output_dir
        self.nfe_output_dir = nfe_output_dir
        self.nfce_output_dir = nfce_output_dir
        self.nfce_base_spreadsheet_path = nfce_base_spreadsheet_path
        self.nfe_max_workers = nfe_max_workers

    def run(
        self,
        selected_rows: list[SpreadsheetRow],
        tabs_by_row_number: dict[int, list[str]],
        month_reference: str,
        year_value: str,
        output_spreadsheet_path: Path | None,
        on_stage_started: Callable[[str, int], None] | None = None,
        on_siga_row_processed: Callable[[int, int], None] | None = None,
        on_nfe_planilha_concluida: Callable[[MeudanfeBatchResult], None] | None = None,
        on_nfce_row_processed: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
        pause_event: threading.Event | None = None,
    ) -> ChainExtractionResult:
        result = ChainExtractionResult()

        # -------------------------------------------------------- etapa 1 de 3: SIGA
        if on_stage_started is not None:
            on_stage_started("siga", 0)
        narrate("Etapa 1 de 3: extração SIGA...")

        self.settings.output_dir = self.siga_output_dir
        siga_extractor = SigaContributorExtractor(
            self.settings,
            allow_manual_login_prompt=False,
            output_spreadsheet_path=output_spreadsheet_path,
        )
        flow = SigaLoginFlow(self.settings)
        with BrowserSession(self.settings) as context:
            authenticated_page = flow.confirm_authenticated_context(context, browser=context.browser)
            narrate_success("Login confirmado: %s", authenticated_page.title())
            result.siga_results = siga_extractor.run_batch_from_spreadsheet_in_context(
                context,
                selected_rows,
                month_reference,
                year_value,
                selected_tabs=None,
                selected_tabs_by_row_number=tabs_by_row_number,
                on_row_processed=on_siga_row_processed,
                cancel_event=cancel_event,
                pause_event=pause_event,
            )

        # O navegador de depuração persistente (reaproveitado via CDP) não é fechado
        # pelo __exit__ do BrowserSession acima (owns_driver=False) — ficaria parado só
        # consumindo RAM durante toda a etapa NF-e a seguir, que não depende dele. A
        # etapa NFC-e mais adiante não precisa do MESMO processo: o login lá é automático
        # (CPF/senha), então basta deixar o próprio BrowserSession da etapa 3 abrir um
        # navegador novo (self-contained, owns_driver=True) quando não achar mais o CDP
        # disponível — e esse, ao final, se fecha sozinho.
        narrate("Encerrando o navegador da etapa SIGA para liberar memória antes da etapa NF-e...")
        terminate_browser_processes(self.settings)

        if cancel_event is not None and cancel_event.is_set():
            narrate_warning("Cadeia encerrada pelo usuário após a etapa SIGA.")
            return result
        narrate_success("Etapa 1 concluída: %s contribuinte(s) processado(s).", len(result.siga_results))

        # ------------------------------------------------------- etapa 2 de 3: NF-e
        if on_stage_started is not None:
            on_stage_started("nfe", 40)
        narrate("Etapa 2 de 3: extração NF-e (Meu DANFE), usando a saída do SIGA como entrada...")

        self.settings.nf_meudanfe_max_workers = self.nfe_max_workers
        nfe_extractor = MeudanfeBatchExtractor(
            self.settings, input_folder=self.siga_output_dir, output_folder=self.nfe_output_dir
        )
        result.nfe_results = nfe_extractor.executar_lote(
            cancelar_evento=cancel_event,
            pausar_evento=pause_event,
            on_planilha_concluida=on_nfe_planilha_concluida,
        )
        if cancel_event is not None and cancel_event.is_set():
            narrate_warning("Cadeia encerrada pelo usuário após a etapa NF-e.")
            return result
        narrate_success("Etapa 2 concluída: %s planilha(s) de NF-e processada(s).", len(result.nfe_results))

        # ------------------------------------------------------ etapa 3 de 3: NFC-e
        if on_stage_started is not None:
            on_stage_started("nfce", 70)
        narrate("Etapa 3 de 3: extração NFC-e, usando a saída do SIGA como pasta de chaves...")

        self.settings.output_dir = self.nfce_output_dir
        self.settings.nfce_keys_folder_path = self.siga_output_dir
        self.settings.nfce_base_spreadsheet_path = self.nfce_base_spreadsheet_path
        nfce_extractor = NfceBatchExtractor(
            self.settings,
            output_dir=self.nfce_output_dir,
            keys_folder=self.siga_output_dir,
            base_spreadsheet_path=self.nfce_base_spreadsheet_path,
        )
        with BrowserSession(self.settings) as context:
            nfce_rows_raw = nfce_extractor.discover_selectable_companies(
                context, cancel_event=cancel_event, pause_event=pause_event
            )
            if not nfce_rows_raw:
                narrate_warning(
                    "Nenhuma empresa elegível para NFC-e (sem IE/CNPJ correspondente na planilha-base, "
                    "ou sem chaves na saída do SIGA)."
                )
            else:
                nfce_rows = [
                    SpreadsheetRow(
                        row_number=int(raw["row_number"]),
                        cnpj=str(raw.get("cnpj") or ""),
                        cod=str(raw.get("cod") or ""),
                        empresa=str(raw.get("empresa") or ""),
                    )
                    for raw in nfce_rows_raw
                ]
                result.nfce_results = nfce_extractor.run_batch_in_context(
                    context,
                    nfce_rows,
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                    on_row_processed=on_nfce_row_processed,
                )
        narrate_success("Etapa 3 concluída: %s empresa(s) de NFC-e processada(s).", len(result.nfce_results))

        narrate_success("Cadeia completa (SIGA → NF-e → NFC-e) concluída.")
        return result
