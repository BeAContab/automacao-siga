from __future__ import annotations

"""Extração de XML de NFC-e via login automático no portal da SEFAZ-CE.

Porta a lógica de negócio de `importação/NFCE/codigo-fonte/xml nfce.py` (login,
gestão de sessão, download por chave de acesso de 44 dígitos) para usar
`BrowserSession`/`selenium_compat.py` em vez do gerenciamento próprio de
Chrome/driver do script original — o próprio `GerenciadorSessao.iniciar_chrome`/
`conectar_selenium` daquele arquivo é redundante com `src/utils/browser.py`.

O arquivo-fonte original nunca é importado ou copiado para dentro deste módulo:
ele contém um CPF e uma senha de contador em texto puro (hardcoded), então toda
portagem é reescrita manual — aqui as credenciais só vêm de `Settings.nfce_cpf`/
`Settings.nfce_senha`, preenchidos em runtime a partir de campos na GUI
(`src/gui.py`, `nfce_cpf_var`/`nfce_senha_var`) e nunca persistidos em disco.
"""

from dataclasses import dataclass
from pathlib import Path
import logging
import re
import shutil
import threading
import time

from openpyxl import load_workbook

from src.config import Settings
from src.extraction.spreadsheet import SpreadsheetRow
from src.utils.execution_control import wait_if_paused
from src.utils.narration import narrate, narrate_error, narrate_success, narrate_warning
from src.utils.selenium_compat import BrowserContext, Error, Page, TimeoutError, UnexpectedAlertError

LOGGER = logging.getLogger(__name__)


def _only_digits(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_cnpj(value: str) -> str:
    digits = _only_digits(value)
    return digits.zfill(14)[-14:] if digits else ""


def normalize_ie(value: str) -> str:
    text = str(value or "").strip().replace("\xa0", " ")
    upper = text.upper()
    if not text or "S/ INSCRI" in upper or "SEM INSCRI" in upper:
        return ""
    return _only_digits(text).lstrip("0")


def sanitize_folder_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "SEM-NOME"


def _is_nfce_key(digits: str) -> bool:
    """True se a sequência é uma chave de acesso de 44 dígitos do modelo NFC-e (65).

    Posições 21-22 (índice [20:22]) da chave de acesso identificam o modelo do
    documento fiscal no padrão nacional: 65 = NFC-e, 55 = NF-e, 57 = CT-e. NF-e, NFC-e
    e CT-e usam o mesmo formato de 44 dígitos, então essa checagem é a rede de
    segurança que impede uma chave de NF-e/CT-e (ex.: achada por engano numa pasta
    'NF-e'/'CT-e' vizinha) de ser tratada como chave de NFC-e.
    """
    return len(digits) == 44 and digits[20:22] == "65"


def extract_keys_from_spreadsheet(path: Path) -> list[str]:
    """Varre todas as colunas/linhas em busca de chaves de acesso de NFC-e (44 dígitos, modelo 65)."""
    keys: list[str] = []
    seen: set[str] = set()
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        for row in sheet.iter_rows(values_only=True):
            for cell in row:
                if cell is None:
                    continue
                digits = _only_digits(str(cell))
                if _is_nfce_key(digits) and digits not in seen:
                    seen.add(digits)
                    keys.append(digits)
        workbook.close()
    except Exception:  # noqa: BLE001
        LOGGER.exception("Falha ao ler chaves da planilha %s", path)
    return keys


def _company_folder_for_cnpj(keys_folder: Path, cnpj: str) -> Path | None:
    """Subpasta direta de `keys_folder` cujo nome contém o CNPJ (convenção do modo SIGA:
    'COD - EMPRESA - CNPJ', ver `_build_taxpayer_folder_name` em `siga_extractor.py`)."""
    normalized = normalize_cnpj(cnpj)
    if not normalized or not keys_folder.is_dir():
        return None
    for candidate in keys_folder.iterdir():
        if candidate.is_dir() and normalized in _only_digits(candidate.name):
            return candidate
    return None


def find_keys_files_for_cnpj(keys_folder: Path, cnpj: str) -> list[Path]:
    """Localiza os arquivos de chaves NFC-e de uma empresa, aceitando dois formatos:

    - Pasta de resultado do SIGA: a subpasta '<COD> - <EMPRESA> - <CNPJ>' contém uma
      ou mais subpastas chamadas exatamente 'NFC-e' (uma por mês, em qualquer
      profundidade — ver `_build_taxpayer_output_dir` em `siga_extractor.py`). Só
      arquivos dentro dessas pastas entram; pastas irmãs 'NF-e'/'CT-e' (mesmo formato
      de chave de 44 dígitos) nunca são varridas.
    - Formato antigo: um arquivo .xlsx solto direto em `keys_folder`, nomeado com o CNPJ.

    Devolve a união dos dois formatos, sem duplicar.
    """
    normalized = normalize_cnpj(cnpj)
    if not normalized or not keys_folder.is_dir():
        return []

    files: list[Path] = []
    company_folder = _company_folder_for_cnpj(keys_folder, cnpj)
    if company_folder is not None:
        for item in company_folder.rglob("*"):
            if item.is_dir() and item.name.strip().lower() == "nfc-e":
                files.extend(sorted(item.glob("*.xlsx")))

    for candidate in keys_folder.glob("*.xlsx"):
        if normalized in _only_digits(candidate.stem):
            files.append(candidate)

    seen_paths: set[Path] = set()
    unique_files: list[Path] = []
    for f in files:
        if f not in seen_paths:
            seen_paths.add(f)
            unique_files.append(f)
    return unique_files


def collect_nfce_keys_for_cnpj(keys_folder: Path, cnpj: str) -> list[str]:
    """Agrega, sem duplicar, as chaves NFC-e válidas de todos os arquivos encontrados
    para o CNPJ (pasta de resultado do SIGA e/ou arquivo solto no formato antigo)."""
    keys: list[str] = []
    seen: set[str] = set()
    for path in find_keys_files_for_cnpj(keys_folder, cnpj):
        for key in extract_keys_from_spreadsheet(path):
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def load_cnpj_ie_base(path: Path | None) -> dict[str, str]:
    """Lê a planilha-base (colunas CNPJ/IE) e devolve um mapa cnpj_normalizado -> ie_normalizada."""
    if path is None or not path.exists():
        return {}
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        header = [str(cell.value or "").strip().upper() for cell in next(sheet.iter_rows(max_row=1))]
        try:
            cnpj_index = header.index("CNPJ")
            ie_index = header.index("IE")
        except ValueError:
            LOGGER.warning("Planilha-base NFC-e sem colunas CNPJ/IE: %s", path)
            workbook.close()
            return {}

        mapa: dict[str, str] = {}
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if len(row) <= max(cnpj_index, ie_index):
                continue
            cnpj = normalize_cnpj(row[cnpj_index])
            ie = normalize_ie(row[ie_index])
            if cnpj:
                mapa[cnpj] = ie
        workbook.close()
        return mapa
    except Exception:  # noqa: BLE001
        LOGGER.exception("Falha ao ler a planilha-base de IE/CNPJ %s", path)
        return {}


@dataclass(slots=True)
class NfceCompanyLink:
    """Uma empresa disponível na área autenticada do portal, raspada após o login."""

    ie: str
    nome: str
    href: str  # script "javascript:..." que abre a aba de detalhe da empresa


@dataclass(slots=True)
class NfceBatchResult:
    """Resultado do processamento de uma linha (empresa) do lote NFC-e."""

    spreadsheet_row: SpreadsheetRow
    status: str  # "concluido" | "parcial" | "sem_chaves" | "sem_empresa" | "erro"
    chaves_total: int = 0
    chaves_baixadas: int = 0
    detalhe: str = ""


class NfceSessionManager:
    """Login, navegação e renovação de sessão no portal da SEFAZ-CE via selenium_compat."""

    def __init__(self, settings: Settings, page: Page) -> None:
        self.settings = settings
        self.page = page
        self._login_time: float | None = None

    def _describe_unexpected_alert(self, exc: UnexpectedAlertError) -> str:
        """Fecha o alerta nativo que interrompeu o comando e monta uma mensagem clara.

        O alerta mais comum aqui e o "Tempo limite excedido! Sera necessario reiniciar a
        operacao" do proprio portal da SEFAZ-CE — ele aparece tanto por expiracao real de
        sessao quanto quando ja existe OUTRA sessao ativa com o mesmo CPF (o portal derruba
        a sessao nova). O codigo nao tem como diferenciar as duas causas a partir do texto
        do alerta sozinho, entao a mensagem cobre as duas.
        """
        alert_text = (getattr(exc, "alert_text", None) or "").strip()
        dismissed_text = (self.page.dismiss_alert_if_present() or "").strip()
        alert_text = alert_text or dismissed_text
        detalhe = f' ("{alert_text}")' if alert_text else ""
        return (
            f"O portal SEFAZ-CE encerrou a sessão inesperadamente{detalhe}. Isso costuma "
            "acontecer quando já existe outra sessão ativa com o mesmo CPF em outro "
            "computador ou navegador — feche a outra sessão e tente novamente."
        )

    def fazer_login(self) -> bool:
        """Efetua login com CPF/senha (settings.nfce_cpf/nfce_senha); idempotente se já logado."""
        # Checa a pagina ATUAL antes de navegar para qualquer lugar: se esta chamada
        # vem logo apos `discover_selectable_companies` (mesmo navegador, sessao ja
        # autenticada, parado na area de empresas), navegar de novo para
        # nfce_login_url tem comportamento imprevisivel no portal (o redirecionamento
        # pode nao cair nem na area de empresas nem na tela de login, derrubando as 3
        # tentativas abaixo com "elemento #txtUsuario nao encontrado"). Reaproveitar a
        # sessao pela pagina atual evita esse ponto de falha por completo.
        try:
            if self.page.locator("xpath=//a[contains(@href,'submete')]").count() > 0:
                LOGGER.info("Usuario NFC-e ja estava logado (sessao reaproveitada)")
                self._login_time = time.time()
                return True
        except Error:
            pass

        for tentativa in range(1, 4):
            try:
                self.page.goto(
                    self.settings.nfce_login_url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.timeout_ms,
                )
                self.page.wait_for_timeout(1500)

                if self.page.locator("xpath=//a[contains(@href,'submete')]").count() > 0:
                    LOGGER.info("Usuario NFC-e ja estava logado")
                    self._login_time = time.time()
                    return True

                self.page.locator("#txtUsuario").fill(self.settings.nfce_cpf or "")
                self.page.locator("#txtSenha").fill(self.settings.nfce_senha or "")
                # Seleciona o perfil "CONTADOR" no dropdown de acesso (posição fixa no
                # formulário do portal, igual ao script original).
                self.page.evaluate(
                    """
                    () => {
                        const select = document.evaluate(
                            "/html/body/div/div[2]/div[2]/div/div[2]/form/table/tbody/tr[3]/td/select",
                            document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                        ).singleNodeValue;
                        if (!select) return;
                        const options = Array.from(select.options);
                        const match = options.find((o) => o.text.trim().toUpperCase() === "CONTADOR");
                        select.value = (match || options[1] || options[0]).value;
                        select.dispatchEvent(new Event("change"));
                    }
                    """
                )
                self.page.locator("#btEntrar").click()
                self.page.wait_for_timeout(4000)
            except UnexpectedAlertError as exc:
                # Causa externa (ex.: outra sessao ja ativa com o mesmo CPF) — repetir o
                # login aqui nao resolve, entao falha na hora em vez de gastar as 3
                # tentativas com o mesmo alerta bloqueando o navegador toda vez.
                message = self._describe_unexpected_alert(exc)
                LOGGER.warning("Alerta inesperado do portal durante o login NFC-e: %s", message)
                narrate_error(message)
                return False
            except Error as exc:
                LOGGER.warning("Tentativa %s de login NFC-e falhou: %s", tentativa, exc)
                self.page.wait_for_timeout(2000)
                continue

            if "erro" not in self.page.url.lower():
                LOGGER.info("Login NFC-e realizado com sucesso na tentativa %s", tentativa)
                self._login_time = time.time()
                return True

        return False

    def acessar_area_empresas(self) -> None:
        try:
            self.page.goto(
                self.settings.nfce_empresas_url,
                wait_until="domcontentloaded",
                timeout=self.settings.timeout_ms,
            )
            self.page.wait_for_timeout(1500)
        except UnexpectedAlertError as exc:
            message = self._describe_unexpected_alert(exc)
            LOGGER.warning("Alerta inesperado do portal ao acessar a área de empresas: %s", message)
            raise RuntimeError(message) from exc

    def sessao_expirando(self) -> bool:
        """True se o login já está velho o suficiente para renovar antes do portal derrubar."""
        if self._login_time is None:
            return True
        return (time.time() - self._login_time) >= self.settings.nfce_session_renewal_seconds

    def renovar_login(self) -> bool:
        """Reloga proativamente (logout + login) para evitar o "Tempo limite excedido" do portal."""
        narrate_warning("Renovando a sessão do portal SEFAZ-CE proativamente...")
        try:
            self.page.goto(
                self.settings.nfce_logout_url,
                wait_until="domcontentloaded",
                timeout=self.settings.timeout_ms,
            )
            self.page.wait_for_timeout(1500)
        except Error:
            pass

        if self.fazer_login():
            self.acessar_area_empresas()
            narrate_success("Sessão do portal SEFAZ-CE renovada com sucesso.")
            return True
        narrate_warning("Não foi possível renovar a sessão proativamente.")
        return False

    def reset_completo_com_espera(self) -> bool:
        """Protocolo de recuperação total: logout + espera longa + login do zero.

        A espera (~4 minutos por padrão) é intencional: dá tempo do portal liberar a
        sessão anterior por completo antes de tentar um novo login, evitando um segundo
        "Tempo limite excedido" imediato.
        """
        wait_minutes = self.settings.nfce_session_recovery_wait_seconds // 60
        narrate_warning(
            "Sessão do portal SEFAZ-CE instável; iniciando protocolo de recuperação "
            "(aguarde cerca de %s minuto(s), isso é esperado)...",
            wait_minutes,
        )
        try:
            self.page.goto(
                self.settings.nfce_logout_url,
                wait_until="domcontentloaded",
                timeout=self.settings.timeout_ms,
            )
        except Error:
            pass
        self.page.wait_for_timeout(self.settings.nfce_session_recovery_wait_seconds * 1000)

        if self.fazer_login():
            self.acessar_area_empresas()
            narrate_success("Protocolo de recuperação concluído; sessão restabelecida.")
            return True
        narrate_error("Protocolo de recuperação falhou; sessão não pôde ser restabelecida.")
        return False

    def listar_empresas(self) -> list[NfceCompanyLink]:
        """Raspa a lista de empresas vinculadas ao CPF logado (IE + nome + link de abertura)."""
        try:
            raw = (
                self.page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll("a[href*='submete']"))
                        .map((a) => ({ text: (a.innerText || "").trim(), href: a.getAttribute("href") || "" }))
                        .filter((item) => item.text)
                    """
                )
                or []
            )
        except UnexpectedAlertError as exc:
            message = self._describe_unexpected_alert(exc)
            LOGGER.warning("Alerta inesperado do portal ao listar as empresas: %s", message)
            raise RuntimeError(message) from exc

        agrupados: dict[str, dict[str, str]] = {}
        for item in raw:
            href = item["href"]
            texto = item["text"]
            registro = agrupados.setdefault(href, {"ie": "", "nome": ""})
            limpo = texto.replace(".", "").replace("-", "").replace("/", "")
            if limpo.isdigit():
                registro["ie"] = texto
            else:
                partes = texto.split(" ", 1)
                if len(partes) > 1 and partes[0].replace(".", "").replace("-", "").isdigit():
                    registro["ie"] = partes[0]
                    registro["nome"] = partes[1]
                else:
                    registro["nome"] = texto

        return [
            NfceCompanyLink(ie=dados["ie"] or "N/A", nome=dados["nome"] or "N/A", href=href)
            for href, dados in agrupados.items()
        ]


class NfceDownloadManager:
    """Detecta o XML baixado (via BrowserContext) e move para a pasta da empresa."""

    def __init__(self, context: BrowserContext, empresa_dir: Path) -> None:
        self.context = context
        self.empresa_dir = empresa_dir
        self.empresa_dir.mkdir(parents=True, exist_ok=True)

    def mover_arquivo(self, origem: Path, chave: str) -> Path:
        # Garante que o nome final sempre carregue a chave, mesmo que o portal sirva
        # um nome genérico — facilita conferir depois qual XML corresponde a qual chave.
        nome_arquivo = origem.name if chave in origem.stem else f"{chave}{origem.suffix}"
        destino = self.empresa_dir / nome_arquivo
        contador = 1
        while destino.exists():
            destino = self.empresa_dir / f"{destino.stem}_{contador}{destino.suffix}"
            contador += 1
        shutil.move(str(origem), str(destino))
        return destino


class NfceBatchExtractor:
    """Orquestra login, raspagem de empresas e download em lote de XMLs de NFC-e."""

    def __init__(
        self,
        settings: Settings,
        output_dir: Path,
        keys_folder: Path,
        base_spreadsheet_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.output_dir = output_dir
        self.keys_folder = keys_folder
        self.base_spreadsheet_path = base_spreadsheet_path

    def run_batch_in_context(
        self,
        context: BrowserContext,
        selected_rows: list[SpreadsheetRow],
        cancel_event: threading.Event | None = None,
        pause_event: threading.Event | None = None,
    ) -> list[NfceBatchResult]:
        page = context.pages[0] if context.pages else context.new_page()
        session = NfceSessionManager(self.settings, page)

        narrate("Fazendo login no portal SEFAZ-CE (modo NFC-e)...")
        if not session.fazer_login():
            narrate_error("Não foi possível fazer login no portal SEFAZ-CE com as credenciais configuradas.")
            raise RuntimeError("Falha no login automático do modo NFC-e.")
        narrate_success("Login no portal SEFAZ-CE realizado com sucesso.")

        narrate("Carregando lista de empresas vinculadas ao CPF...")
        session.acessar_area_empresas()
        empresas = session.listar_empresas()
        narrate_success("%s empresa(s) encontrada(s) na sessão.", len(empresas))

        mapa_cnpj_ie = load_cnpj_ie_base(self.base_spreadsheet_path)
        mapa_ie_cnpj = {ie: cnpj for cnpj, ie in mapa_cnpj_ie.items() if ie}

        results: list[NfceBatchResult] = []
        for index, spreadsheet_row in enumerate(selected_rows, start=1):
            if not wait_if_paused(cancel_event, pause_event):
                LOGGER.info("Lote NFC-e encerrado a pedido do usuario antes da proxima empresa.")
                narrate_warning("Execução encerrada pelo usuário.")
                break

            target_cnpj = normalize_cnpj(spreadsheet_row.cnpj)
            empresa_nome = spreadsheet_row.empresa or "SEM-EMPRESA"
            narrate(
                "Processando empresa %s de %s: %s (CNPJ %s)...",
                index,
                len(selected_rows),
                empresa_nome,
                spreadsheet_row.cnpj,
            )

            company = self._match_company(empresas, target_cnpj, mapa_ie_cnpj)
            if company is None:
                narrate_warning("Empresa %s não encontrada na sessão do portal SEFAZ-CE.", empresa_nome)
                results.append(NfceBatchResult(spreadsheet_row, status="sem_empresa"))
                continue

            chaves = collect_nfce_keys_for_cnpj(self.keys_folder, target_cnpj)
            if not chaves:
                narrate_warning(
                    "Nenhuma chave de NFC-e encontrada para %s na pasta configurada "
                    "(nem em subpasta 'NFC-e' de resultado do SIGA, nem em planilha solta).",
                    empresa_nome,
                )
                results.append(NfceBatchResult(spreadsheet_row, status="sem_chaves"))
                continue

            narrate("%s chave(s) a processar para %s.", len(chaves), empresa_nome)
            empresa_dir = self.output_dir / sanitize_folder_name(f"{company.ie} - {empresa_nome}")
            baixadas = self._processar_empresa(
                context, page, session, company, chaves, empresa_dir, cancel_event, pause_event
            )

            status = "concluido" if baixadas == len(chaves) else "parcial"
            if status == "concluido":
                narrate_success("Empresa %s concluída: %s de %s chave(s) baixadas.", empresa_nome, baixadas, len(chaves))
            else:
                narrate_warning("Empresa %s incompleta: %s de %s chave(s) baixadas.", empresa_nome, baixadas, len(chaves))
            results.append(
                NfceBatchResult(
                    spreadsheet_row,
                    status=status,
                    chaves_total=len(chaves),
                    chaves_baixadas=baixadas,
                )
            )

        return results

    def discover_selectable_companies(self, context: BrowserContext) -> list[dict]:
        """Loga no portal e devolve as empresas elegíveis para a tela de seleção.

        Elegível = a IE devolvida pelo portal resolve para um CNPJ na planilha-base
        IE/CNPJ *e* esse CNPJ tem um arquivo de chaves correspondente na pasta
        configurada (com pelo menos uma chave válida). Usado só para popular a grade
        antes da execução; `run_batch_in_context` refaz login/listagem do zero por
        conta própria (idempotente, já que `fazer_login` detecta sessão já ativa).
        """
        page = context.pages[0] if context.pages else context.new_page()
        session = NfceSessionManager(self.settings, page)

        narrate("Fazendo login no portal SEFAZ-CE (modo NFC-e)...")
        if not session.fazer_login():
            narrate_error("Não foi possível fazer login no portal SEFAZ-CE com as credenciais configuradas.")
            raise RuntimeError("Falha no login automático do modo NFC-e.")
        narrate_success("Login no portal SEFAZ-CE realizado com sucesso.")

        session.acessar_area_empresas()
        empresas = session.listar_empresas()
        narrate("%s empresa(s) encontrada(s) na sessão do portal.", len(empresas))

        mapa_cnpj_ie = load_cnpj_ie_base(self.base_spreadsheet_path)
        mapa_ie_cnpj = {ie: cnpj for cnpj, ie in mapa_cnpj_ie.items() if ie}

        rows: list[dict] = []
        for index, company in enumerate(empresas, start=1):
            cnpj = mapa_ie_cnpj.get(normalize_ie(company.ie), "")
            if not cnpj:
                continue
            chaves = collect_nfce_keys_for_cnpj(self.keys_folder, cnpj)
            if not chaves:
                continue
            rows.append(
                {
                    "row_number": index,
                    "cod": company.ie,
                    "empresa": company.nome,
                    "cnpj": cnpj,
                    "chaves_count": len(chaves),
                }
            )

        narrate_success("%s empresa(s) elegível(is) para download (com chaves disponíveis).", len(rows))
        return rows

    def _match_company(
        self,
        empresas: list[NfceCompanyLink],
        target_cnpj: str,
        mapa_ie_cnpj: dict[str, str],
    ) -> NfceCompanyLink | None:
        for company in empresas:
            ie_normalizada = normalize_ie(company.ie)
            if mapa_ie_cnpj.get(ie_normalizada) == target_cnpj:
                return company
        return None

    def _processar_empresa(
        self,
        context: BrowserContext,
        page: Page,
        session: NfceSessionManager,
        company: NfceCompanyLink,
        chaves: list[str],
        empresa_dir: Path,
        cancel_event: threading.Event | None = None,
        pause_event: threading.Event | None = None,
    ) -> int:
        """Processa as chaves de uma empresa, com renovação de sessão e recuperação em falha.

        Preserva as três defesas do script original: renovação proativa por tempo
        (evita o "Tempo limite excedido" do portal), reset completo em erro crítico
        (sessão realmente caída) e limite de passadas para não entrar em loop infinito
        com chaves que nunca baixam (canceladas/denegadas/inexistentes na SEFAZ).
        """
        download_manager = NfceDownloadManager(context, empresa_dir)
        pendentes = list(chaves)
        baixadas: set[str] = set()
        passadas_sem_progresso = 0

        for _passada in range(5):
            if not pendentes:
                break
            if not wait_if_paused(cancel_event, pause_event):
                LOGGER.info("Processamento de %s encerrado a pedido do usuario.", company.nome)
                break

            if session.sessao_expirando():
                session.renovar_login()

            script = company.href.replace("javascript:", "")
            try:
                empresa_page = self._abrir_empresa(page, script)
            except (Error, TimeoutError) as exc:
                LOGGER.warning("Falha ao abrir a empresa %s: %s", company.nome, exc)
                if not (session.renovar_login() or session.reset_completo_com_espera()):
                    break
                continue

            progresso_nesta_passada = 0
            try:
                for chave_index, chave in enumerate(list(pendentes), start=1):
                    if not wait_if_paused(cancel_event, pause_event):
                        LOGGER.info("Processamento de %s encerrado a pedido do usuario.", company.nome)
                        return len(baixadas)

                    if chave_index % self.settings.nfce_session_renewal_check_every_n_keys == 0 and session.sessao_expirando():
                        narrate("Renovando sessão antes de continuar o lote de %s...", company.nome)
                        break

                    sucesso, precisa_reset = self._baixar_xml_chave(context, empresa_page, chave, download_manager)
                    if sucesso:
                        baixadas.add(chave)
                        pendentes.remove(chave)
                        progresso_nesta_passada += 1
                    if precisa_reset:
                        narrate_warning("Sessão instável durante o download de %s; acionando recuperação.", company.nome)
                        if not (session.renovar_login() or session.reset_completo_com_espera()):
                            return len(baixadas)
                        break
            finally:
                # Sempre fecha a aba da empresa ao fim da passada (sucesso, falha ou
                # reset) e volta pra lista — a próxima passada reabre a empresa do
                # zero, mesmo padrão do script original. Sem isso, cada passada
                # acumularia mais uma aba aberta.
                self._fechar_aba_empresa(empresa_page, page)

            if progresso_nesta_passada == 0:
                passadas_sem_progresso += 1
            else:
                passadas_sem_progresso = 0
            if passadas_sem_progresso >= 3:
                narrate_warning(
                    "%s chave(s) de %s não baixaram após tentativas repetidas "
                    "(provavelmente canceladas/denegadas/inexistentes na SEFAZ).",
                    len(pendentes),
                    company.nome,
                )
                break

        return len(baixadas)

    def _abrir_empresa(self, page: Page, script: str) -> Page:
        """Executa o script de abertura da empresa e navega para a consulta de NFC-e.

        O script (`javascript:submete(...)` raspado do portal) abre a empresa numa
        aba/janela NOVA via `window.open()` — nunca navega a aba atual. Precisa
        detectar essa aba nova (comparando os handles antes/depois) e devolvê-la,
        já que a aba original (lista de empresas) nunca vai ter o link "Consultar
        NFC-e". `launch_debug_browser` já abre o Chrome com `--disable-popup-blocking`
        para esse pop-up não ser bloqueado.
        """
        handles_antes = set(page.driver.window_handles)
        page.evaluate(script)
        page.wait_for_timeout(1500)

        novos_handles = [h for h in page.driver.window_handles if h not in handles_antes]
        if not novos_handles:
            raise TimeoutError(
                "A empresa não abriu uma aba nova (pop-up pode ter sido bloqueado pelo navegador)."
            )
        empresa_page = Page(page.context, novos_handles[0])

        empresa_page.evaluate(
            """
            () => {
                document.querySelectorAll('.mfe-migration-modal, .modal-backdrop, .modal').forEach((el) => el.remove());
                document.body.classList.remove('modal-open');
                document.body.style.overflow = 'auto';
            }
            """
        )
        link = empresa_page.locator("a[ui-sref='taxpayers.fiscalCouponsNfceList']")
        link.wait_for(state="visible", timeout=10_000)
        link.click(force=True)
        empresa_page.wait_for_timeout(2000)
        return empresa_page

    def _fechar_aba_empresa(self, empresa_page: Page, pagina_lista: Page) -> None:
        """Fecha a aba da empresa (aberta por `_abrir_empresa`) e volta para a lista."""
        driver = empresa_page.driver
        try:
            if empresa_page.handle in driver.window_handles:
                driver.switch_to.window(empresa_page.handle)
                driver.close()
        except Error:
            pass
        finally:
            if pagina_lista.handle in driver.window_handles:
                driver.switch_to.window(pagina_lista.handle)

    def _baixar_xml_chave(
        self,
        context: BrowserContext,
        page: Page,
        chave: str,
        download_manager: NfceDownloadManager,
    ) -> tuple[bool, bool]:
        """Consulta uma chave e baixa o XML. Retorna (sucesso, precisa_reset_de_sessao)."""
        try:
            page.evaluate(
                """
                (chave) => {
                    document.querySelectorAll('.modal-backdrop, .modal').forEach((el) => el.remove());
                    const input = document.getElementById('nfceKey');
                    if (input) {
                        input.value = chave;
                        input.dispatchEvent(new Event('input'));
                    }
                    const button = document.querySelector('button[ng-click="find()"]');
                    if (button) button.click();
                }
                """,
                chave,
            )

            resultados = page.locator("#table-search-coupons")
            resultados.wait_for(state="visible", timeout=10_000)

            achou_link = page.evaluate(
                """
                () => {
                    const rows = document.querySelectorAll('#table-search-coupons tbody tr');
                    if (rows.length === 0 || (rows.length === 1 && rows[0].innerText.includes('Nenhum registro'))) return false;
                    const link = rows[0].querySelector('a');
                    if (link) { link.click(); return true; }
                    return false;
                }
                """
            )
            if not achou_link:
                return False, False

            botao_xml = page.locator("button[ng-click='downloadXML()']")
            botao_xml.wait_for(state="visible", timeout=10_000)

            snapshot = context.download_snapshot()
            botao_xml.click(force=True)
            try:
                downloaded_path = context.wait_for_download(snapshot, timeout_ms=15_000)
            except TimeoutError:
                return False, False

            download_manager.mover_arquivo(downloaded_path, chave)

            page.evaluate(
                """
                () => {
                    document.querySelectorAll('.modal-backdrop, .modal').forEach((el) => el.remove());
                }
                """
            )
            return True, False
        except TimeoutError:
            return False, False
        except Error as exc:
            texto_erro = str(exc).lower()
            precisa_reset = "disconnected" in texto_erro or "stacktrace" in texto_erro or "script timeout" in texto_erro
            LOGGER.warning("Falha ao baixar a chave %s: %s", chave, exc)
            return False, precisa_reset
