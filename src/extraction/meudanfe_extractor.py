from __future__ import annotations

"""Extração de XML/PDF de NF-e via consulta pública por chave de acesso no Meu DANFE.

Porta a lógica de negócio de `importação/NFE 2/automacao-meu-danfe/main.py` (driver
`undetected_chromedriver`, resolução do captcha Cloudflare Turnstile, leitura de
planilhas com a coluna "Chave NF-e" e download de XML/PDF) para dentro do projeto
principal como a implementação real do modo NF-e da GUI — substituindo o aviso de
"não implementado" que existia por causa do motor Playwright incompatível do script
`importação/NFE/NFE_XML.py` (ver `brain/2026-08-19-nfe-playwright-nao-integrado.md`).

Diferente de NF-e/NFC-e do SIGA, este módulo **não** usa `BrowserSession`/
`selenium_compat.py`: o Meu DANFE é uma consulta pública anônima (sem login, sem
estado de sessão para compartilhar com o SIGA) e o script original já resolve
paralelismo com várias instâncias independentes de `undetected_chromedriver` — uma
por worker, cada uma com seu próprio perfil e pasta de download temporária. Forçar
isso pelo `BrowserSession` (pensado para uma única sessão persistente via CDP-attach)
arriscaria quebrar a resolução de captcha, que foi estabilizada especificamente contra
as camuflagens do `undetected_chromedriver` (histórico de 6 iterações documentado em
`importação/NFE 2/automacao-meu-danfe/brain/historico.md`). Por isso este módulo
gerencia seus próprios drivers Selenium diretamente.

O paralelismo é preservado, mas limitado a no máximo 4 Chromes simultâneos (o script
original permite até 8) — ver `Settings.nf_meudanfe_max_workers`.

O código de sugestão de navegadores por IA (Gemini/Groq) e a coleta de hardware do
script original são código morto no próprio projeto-fonte (nunca chamados) e não
foram portados. A GUI PySide6 original também não foi portada — este modo usa a
mesma GUI Tkinter do restante do projeto (`src/gui.py`).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import concurrent.futures
import logging
import math
import re
import subprocess
import tempfile
import threading
import time
import unicodedata
import warnings

from openpyxl import load_workbook
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    NoSuchWindowException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import undetected_chromedriver as uc

from src.config import Settings
from src.extraction.nfce_extractor import cnpj_from_access_key, is_nfe_key, sanitize_folder_name
from src.extraction.spreadsheet import (
    DIRECAO_SUBPASTA,
    SpreadsheetRow,
    load_cod_empresa_cnpj_base,
    tipo_nota_do_nome_arquivo,
)
from src.utils.execution_control import wait_if_paused as _aguardar_execucao
from src.utils.narration import narrate, narrate_error, narrate_success, narrate_warning

LOGGER = logging.getLogger(__name__)

COLUNA_CHAVE_NFE = "chave nf-e"
MAX_WORKERS_PERMITIDO = 8

# Serializa a criação do driver entre workers paralelos: o undetected_chromedriver
# faz o patch do binário do chromedriver em disco, e duas criações simultâneas podem
# colidir no Windows (FileExistsError).
_LOCK_INICIALIZACAO_DRIVER = threading.Lock()


def _aguardar_intervalo(
    segundos: float,
    cancelar_evento: threading.Event | None,
    pausar_evento: threading.Event | None,
) -> bool:
    """Espera cooperativa entre passadas do lote - divide em passos de até 1s para checar
    cancelamento/pausa (`wait_if_paused`) sem travar `segundos` inteiros de uma vez.

    Devolve `False` se o usuário cancelar durante a espera; `True` se ela terminar normalmente.
    """
    fim = time.time() + segundos
    while time.time() < fim:
        if not _aguardar_execucao(cancelar_evento, pausar_evento):
            return False
        time.sleep(max(0.0, min(1.0, fim - time.time())))
    return True


def normalizar_texto(valor: object) -> str:
    """Normaliza textos para comparar cabeçalhos sem depender de caixa/espaços."""
    texto = "" if valor is None else str(valor)
    return " ".join(texto.strip().lower().split())


def remover_acentos(valor: object) -> str:
    """Remove acentos para comparações mais robustas com mensagens do site."""
    texto = "" if valor is None else str(valor)
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


def sanitizar_chave(valor: object) -> str:
    """Mantém apenas os dígitos da chave de acesso."""
    return re.sub(r"\D", "", "" if valor is None else str(valor))


def localizar_chrome(caminho_informado: str | Path | None = None) -> Path | None:
    """Localiza o executável do Google Chrome no Windows."""
    if caminho_informado:
        candidatos = [Path(caminho_informado)]
    else:
        candidatos = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
    for candidato in candidatos:
        if candidato.is_file():
            return candidato
    return None


def obter_versao_principal_chrome(executavel: Path | None) -> int | None:
    """Lê a versão principal do Chrome para alinhar o driver ao navegador instalado.

    A compatibilidade entre Chrome e ChromeDriver é sensível à versão principal;
    quando esse valor é conhecido, o undetected_chromedriver consegue se ajustar
    melhor e reduzimos falhas de SessionNotCreatedException.
    """
    if executavel is None or not executavel.exists():
        return None

    comandos = [
        ["powershell", "-NoProfile", "-Command", f"(Get-Item '{executavel}').VersionInfo.ProductVersion"],
        [str(executavel), "--version"],
        [str(executavel), "--product-version"],
    ]
    for comando in comandos:
        try:
            resultado = subprocess.run(comando, capture_output=True, text=True, timeout=10, check=True)
        except Exception:  # noqa: BLE001
            continue
        saida = (resultado.stdout or resultado.stderr or "").strip()
        match = re.search(r"\b(\d{2,3})\b", saida)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


@dataclass(slots=True)
class RegistroPlanilhaNFe:
    """Representa uma chave de acesso localizada numa planilha de origem."""

    caminho_planilha: Path
    pasta_destino: Path
    chave: str
    linha_origem: int


@dataclass(slots=True)
class DocumentoFiscalBaixado:
    """Bytes do PDF e do XML baixados do Meu DANFE para uma chave."""

    pdf_bytes: bytes
    xml_bytes: bytes


@dataclass(slots=True)
class MeudanfeBatchResult:
    """Resultado consolidado do processamento de uma planilha de chaves NF-e."""

    caminho_planilha: Path
    chaves_total: int = 0
    chaves_baixadas: int = 0
    chaves_puladas: int = 0
    chaves_com_falha: int = 0

    @property
    def status(self) -> str:
        """Status final da planilha — só faz sentido chamar depois que o lote inteiro terminou.

        `chaves_com_falha == 0` sozinho não basta para dizer "concluído": se o lote foi
        encerrado (usuário clicou Encerrar, ou algum outro corte cedo), uma planilha cujas
        chaves nunca chegaram a ser tentadas também tem `chaves_com_falha == 0` — sem esse
        campo, ela caía aqui como "concluido" mesmo com 0 de N chaves realmente processadas,
        deixando o resumo do lote ("Planilhas concluídas: X de Y") mentiroso.
        """
        if self.chaves_total == 0:
            return "sem_chaves"
        processadas = self.chaves_baixadas + self.chaves_puladas + self.chaves_com_falha
        if processadas < self.chaves_total:
            return "interrompido"
        if self.chaves_com_falha:
            return "parcial" if (self.chaves_baixadas + self.chaves_puladas) else "erro"
        return "concluido"


def listar_planilhas_nfe(pasta_dados: Path) -> list[Path]:
    """Lista as planilhas .xlsx candidatas a conter chaves de NF-e.

    Se `pasta_dados` for um arquivo único (não uma pasta) — ex. um arquivo solto
    baixado direto para Downloads —, é devolvido direto: o usuário escolheu esse
    arquivo explicitamente, então o filtro por nome não se aplica; quem garante que só
    entram chaves de NF-e é a própria leitura da coluna "Chave NF-e" mais adiante, não o
    nome do arquivo. Se for uma pasta, varre recursivamente e filtra pelo nome conter
    "nf-e", para não misturar por engano planilhas de NFC-e/CT-e soltas na mesma árvore.

    Em qualquer um dos dois casos, ignora arquivos de lock do Excel (`~$arquivo.xlsx`,
    criados enquanto a planilha original está aberta) — não são planilhas de verdade e
    só gerariam um aviso de leitura na tentativa de abri-los.
    """
    if pasta_dados.is_file():
        return [] if pasta_dados.name.startswith("~$") else [pasta_dados]
    if not pasta_dados.is_dir():
        return []
    return sorted(
        caminho
        for caminho in pasta_dados.rglob("*.xlsx")
        if "nf-e" in caminho.name.lower() and not caminho.name.startswith("~$")
    )


def localizar_coluna_chave_nfe(aba) -> tuple[int, int]:
    """Localiza a linha de cabeçalho e a coluna "Chave NF-e" dentro das 10 primeiras linhas."""
    limite_busca = min(10, aba.max_row or 10)
    for indice_linha, linha in enumerate(
        aba.iter_rows(min_row=1, max_row=limite_busca, values_only=True), start=1
    ):
        cabecalhos = [normalizar_texto(valor) for valor in linha]
        if COLUNA_CHAVE_NFE in cabecalhos:
            return indice_linha, cabecalhos.index(COLUNA_CHAVE_NFE) + 1
    raise ValueError("A coluna 'Chave NF-e' não foi encontrada.")


def _pasta_empresa_pelo_caminho(caminho_planilha: Path, pasta_destino_base: Path, pasta_entrada: Path) -> Path | None:
    """Nome da pasta da empresa inferido pelo primeiro segmento do caminho relativo à
    pasta de entrada — convenção `<COD - EMPRESA - CNPJ>/<mês>/[<aba>]/planilha.xlsx` do
    SIGA. Usado como 2ª prioridade em `montar_pasta_destino_chave` (só quando o CNPJ da
    chave não consta na planilha-base). Devolve `None` quando não há esse segmento de
    pasta (planilha solta direto na pasta de entrada, ou a entrada é um arquivo único).
    """
    try:
        partes = caminho_planilha.relative_to(pasta_entrada).parts
    except ValueError:
        # Planilha fora da pasta de entrada esperada (não deveria acontecer, já que
        # `listar_planilhas_nfe` sempre varre a partir dela).
        partes = ()
    return pasta_destino_base / partes[0] if len(partes) > 1 else None


def montar_pasta_destino_chave(
    chave: str,
    caminho_planilha: Path,
    pasta_destino_base: Path,
    pasta_entrada: Path,
    mapa_cod_empresa_cnpj: dict[str, SpreadsheetRow],
    direcao: str = "",
) -> Path:
    """Resolve a pasta de destino de uma chave, na mesma ordem de prioridade documentada
    para o robô de referência que inspirou esta função (planilha "Identificação e
    Organização das Pastas"):

    1. CNPJ do emitente embutido na própria chave (`cnpj_from_access_key`), buscado na
       planilha-base COD/EMPRESA/CNPJ — o mais confiável, porque distingue matriz e
       filiais mesmo quando o nome da pasta de entrada não ajuda (ex.: pastas genéricas
       "0001"/"0002" por filial, sem CNPJ no nome — fora da convenção do SIGA, mas
       possível quando a entrada vem de outra fonte).
    2. Nome da pasta de entrada (`<COD - EMPRESA - CNPJ>/...`, convenção do SIGA) — usado
       só quando o CNPJ da chave não consta na planilha-base.
    3. `SEM-COD - SEM-EMPRESA - <cnpj>`, se nem isso resolver.

    No caso comum (entrada = saída do próprio SIGA, planilha-base atualizada), o
    resultado da prioridade 1 já bate com o nome que o SIGA deu à pasta — a mudança de
    prioridade só se nota nos cenários de exceção acima.

    `direcao` ("saida"/"entrada"/"", já detectada pelo nome do arquivo de origem por
    quem chama) acrescenta a subpasta "Notas de Saída"/"Notas de Entrada" no final.
    """
    cnpj = cnpj_from_access_key(chave)
    info = mapa_cod_empresa_cnpj.get(cnpj)
    if info is not None:
        pasta_empresa = pasta_destino_base / sanitize_folder_name(
            f"{info.cod or 'SEM-COD'} - {info.empresa or 'SEM-EMPRESA'} - {cnpj}"
        )
    else:
        pasta_empresa = _pasta_empresa_pelo_caminho(caminho_planilha, pasta_destino_base, pasta_entrada)
        if pasta_empresa is None:
            pasta_empresa = pasta_destino_base / sanitize_folder_name(f"SEM-COD - SEM-EMPRESA - {cnpj}")
    return pasta_empresa / DIRECAO_SUBPASTA[direcao] if direcao else pasta_empresa


def extrair_registros_planilha_nfe(
    caminho_planilha: Path,
    pasta_destino_base: Path,
    pasta_entrada: Path,
    mapa_cod_empresa_cnpj: dict[str, SpreadsheetRow] | None = None,
) -> list[RegistroPlanilhaNFe]:
    """Extrai as chaves válidas (44 dígitos, modelo NF-e, deduplicadas) de uma planilha e
    sua origem. A pasta de destino é resolvida por CHAVE (`montar_pasta_destino_chave`,
    que prioriza o CNPJ embutido na chave sobre o nome da pasta de entrada), já que uma
    planilha solta pode em tese conter chaves de mais de uma empresa.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Workbook contains no default style, apply openpyxl's default"
        )
        workbook = load_workbook(caminho_planilha, read_only=True, data_only=True)

    try:
        aba = workbook[workbook.sheetnames[0]]
        linha_cabecalho, coluna_chave = localizar_coluna_chave_nfe(aba)
        direcao_planilha = tipo_nota_do_nome_arquivo(caminho_planilha.name)
        registros: list[RegistroPlanilhaNFe] = []
        chaves_vistas: set[str] = set()

        for numero_linha, linha in enumerate(
            aba.iter_rows(min_row=linha_cabecalho + 1, values_only=True), start=linha_cabecalho + 1
        ):
            if len(linha) < coluna_chave:
                continue
            chave = sanitizar_chave(linha[coluna_chave - 1])
            if not chave:
                continue
            if len(chave) != 44:
                LOGGER.warning(
                    "Chave inválida ignorada na planilha %s, linha %s: %s",
                    caminho_planilha.name,
                    numero_linha,
                    chave,
                )
                continue
            if not is_nfe_key(chave):
                LOGGER.warning(
                    "Chave de modelo incorreto ignorada (não é NF-e, provavelmente NFC-e/CT-e) "
                    "na planilha %s, linha %s: %s",
                    caminho_planilha.name,
                    numero_linha,
                    chave,
                )
                continue
            if chave in chaves_vistas:
                continue
            chaves_vistas.add(chave)
            pasta_destino = montar_pasta_destino_chave(
                chave, caminho_planilha, pasta_destino_base, pasta_entrada, mapa_cod_empresa_cnpj or {}, direcao_planilha
            )
            registros.append(
                RegistroPlanilhaNFe(
                    caminho_planilha=caminho_planilha,
                    pasta_destino=pasta_destino,
                    chave=chave,
                    linha_origem=numero_linha,
                )
            )
        return registros
    finally:
        workbook.close()


def arquivos_ja_existem(pasta_destino: Path, chave: str) -> bool:
    """True se o PDF e o XML finais da chave já existem na pasta de destino."""
    return (pasta_destino / "PDF" / f"{chave}.pdf").exists() and (pasta_destino / "XML" / f"{chave}.xml").exists()


def salvar_documentos_fiscais(pasta_destino: Path, chave: str, documento: DocumentoFiscalBaixado) -> tuple[Path, Path]:
    """Salva PDF/XML com nome estável baseado na chave, em subpastas separadas por tipo."""
    pasta_pdf = pasta_destino / "PDF"
    pasta_xml = pasta_destino / "XML"
    pasta_pdf.mkdir(parents=True, exist_ok=True)
    pasta_xml.mkdir(parents=True, exist_ok=True)

    caminho_pdf = pasta_pdf / f"{chave}.pdf"
    caminho_xml = pasta_xml / f"{chave}.xml"
    caminho_pdf.write_bytes(documento.pdf_bytes)
    caminho_xml.write_bytes(documento.xml_bytes)
    return caminho_pdf, caminho_xml


class MeudanfeChromeWorker:
    """Encapsula um driver Chrome (undetected_chromedriver) e a automação de uma chave por vez."""

    def __init__(
        self,
        pasta_download_temporaria: Path,
        tempo_espera_captcha: int,
        tempo_download: int,
        url_base: str,
        chrome_path: str | None = None,
        pausar_evento: threading.Event | None = None,
    ) -> None:
        self.url_base = url_base
        self.pasta_download_temporaria = pasta_download_temporaria
        self.tempo_espera_captcha = tempo_espera_captcha
        self.tempo_download = tempo_download
        self._pausar_evento = pausar_evento
        self.driver = self._criar_driver(chrome_path)
        self.wait = WebDriverWait(self.driver, 20)

    def _criar_driver(self, chrome_path: str | None):
        """Cria um Chrome não detectável usando undetected_chromedriver.

        As correções anti-bot (navigator.webdriver, patches de CDP etc.) são aplicadas
        internamente pelo undetected_chromedriver — não há flags extras a configurar aqui.
        """
        options = uc.ChromeOptions()
        executavel = localizar_chrome(chrome_path)
        if executavel is not None:
            options.binary_location = str(executavel)

        versao_principal = obter_versao_principal_chrome(executavel)
        if versao_principal is not None:
            LOGGER.info("Chrome detectado em %s com versão principal %s.", executavel, versao_principal)
        else:
            LOGGER.info("Não foi possível ler a versão principal do Chrome; seguindo sem ajuste fino.")

        self.pasta_download_temporaria.mkdir(parents=True, exist_ok=True)
        prefs = {
            "download.default_directory": str(self.pasta_download_temporaria.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "profile.default_content_setting_values.automatic_downloads": 1,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_argument("--start-maximized")
        options.add_argument("--disable-popup-blocking")

        try:
            with _LOCK_INICIALIZACAO_DRIVER:
                argumentos_driver: dict[str, object] = {"options": options, "headless": False}
                if versao_principal is not None:
                    argumentos_driver["version_main"] = versao_principal
                driver = uc.Chrome(**argumentos_driver)
        except WebDriverException as erro:
            raise RuntimeError(
                "Não foi possível iniciar o Chrome com undetected_chromedriver. "
                "Verifique se a versão do Chrome instalado é compatível com o driver."
            ) from erro

        self._configurar_pasta_download(self.pasta_download_temporaria, driver)
        return driver

    def fechar(self) -> None:
        """Encerra o navegador desta automação, tolerando exceções de encerramento no Windows."""
        driver = getattr(self, "driver", None)
        if driver is None:
            return
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            LOGGER.debug("Encerramento do Chrome ignorou uma exceção não crítica.", exc_info=True)
        finally:
            try:
                driver.quit = lambda: None  # type: ignore[method-assign]
            except Exception:  # noqa: BLE001
                pass
            self.driver = None

    def _configurar_pasta_download(self, pasta_download: Path, driver=None) -> None:
        """Atualiza a pasta de download via CDP antes de cada chave."""
        pasta_download.mkdir(parents=True, exist_ok=True)
        driver = driver or self.driver
        try:
            driver.execute_cdp_cmd(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(pasta_download.resolve()), "eventsEnabled": False},
            )
        except Exception:  # noqa: BLE001
            driver.execute_cdp_cmd(
                "Page.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(pasta_download.resolve())},
            )

    def _elemento_visivel(self, element_id: str) -> bool:
        try:
            return self.driver.find_element(By.ID, element_id).is_displayed()
        except NoSuchElementException:
            return False

    def _texto_alerta(self) -> str:
        try:
            return self.driver.find_element(By.ID, "alertTxt").text.strip()
        except NoSuchElementException:
            return ""

    def _clicar_com_fallback(self, elemento) -> bool:
        """Tenta um clique nativo e, se falhar, usa ActionChains como contingência."""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", elemento
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            elemento.click()
            return True
        except Exception:  # noqa: BLE001
            try:
                ActionChains(self.driver).move_to_element(elemento).pause(0.2).click().perform()
                return True
            except Exception:  # noqa: BLE001
                return False

    def _preencher_campo_texto(self, elemento, valor: str) -> None:
        """Preenche um campo sem depender de clique/digitação física.

        O site reage melhor quando a chave entra via foco + atribuição de `.value` +
        eventos `input`/`change` disparados manualmente, em vez de `send_keys`.
        """
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", elemento
            )
            self.driver.execute_script("arguments[0].focus();", elemento)
        except Exception:  # noqa: BLE001
            pass
        try:
            elemento.clear()
        except Exception:  # noqa: BLE001
            pass
        self.driver.execute_script(
            "var el = arguments[0]; var valor = arguments[1];"
            "el.value = ''; el.value = valor;"
            "el.dispatchEvent(new Event('input', {bubbles:true}));"
            "el.dispatchEvent(new Event('change', {bubbles:true}));",
            elemento,
            valor,
        )

    def _clicar_com_offset(self, elemento, offset_x: int, offset_y: int) -> bool:
        """Clica num ponto específico dentro do elemento, via CDP e com fallback em ActionChains."""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", elemento
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            posicao = (
                self.driver.execute_script(
                    "var r = arguments[0].getBoundingClientRect();"
                    "return {x: r.left, y: r.top, w: r.width, h: r.height};",
                    elemento,
                )
                or {}
            )
            x = float(posicao.get("x") or 0) + float(offset_x)
            y = float(posicao.get("y") or 0) + float(offset_y)
            for tipo in ("mouseMoved", "mousePressed", "mouseReleased"):
                params: dict[str, object] = {"type": tipo, "x": x, "y": y, "button": "left", "buttons": 1}
                if tipo != "mouseMoved":
                    params["clickCount"] = 1
                self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", params)
            return True
        except Exception:  # noqa: BLE001
            pass
        try:
            ActionChains(self.driver).move_to_element_with_offset(elemento, offset_x, offset_y).click().perform()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _tentar_clicar_captcha(self) -> bool:
        """Tenta clicar no captcha Cloudflare Turnstile sem depender de um único seletor.

        Cadeia de tentativas (histórico V1-V6 em
        `importação/NFE 2/automacao-meu-danfe/brain/historico.md`): busca em iframes
        conhecidos → checkbox → corpo do iframe → `#captchaDiv` diretamente → clique por
        offset dentro do widget (o Turnstile costuma expor o checkbox à esquerda).
        """
        seletores_iframe = [
            "#captchaDiv iframe",
            "iframe[title*='captcha' i]",
            "iframe[title*='human' i]",
            "iframe[src*='captcha' i]",
            "iframe[src*='challenge' i]",
        ]
        seletores_interativos = [
            ".recaptcha-checkbox-border",
            "#checkbox",
            ".ctp-checkbox-container",
            "input[type='checkbox']",
            "[role='checkbox']",
        ]

        try:
            self.driver.switch_to.default_content()
        except Exception:  # noqa: BLE001
            pass

        for seletor_iframe in seletores_iframe:
            for iframe in self.driver.find_elements(By.CSS_SELECTOR, seletor_iframe):
                try:
                    self.driver.switch_to.frame(iframe)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    for seletor in seletores_interativos:
                        for elemento in self.driver.find_elements(By.CSS_SELECTOR, seletor):
                            if elemento.is_displayed() and self._clicar_com_fallback(elemento):
                                return True
                    corpo = self.driver.find_element(By.TAG_NAME, "body")
                    if self._clicar_com_fallback(corpo):
                        return True
                except Exception:  # noqa: BLE001
                    LOGGER.debug("Falha ao tentar clicar no captcha dentro do iframe %s.", seletor_iframe, exc_info=True)
                finally:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:  # noqa: BLE001
                        pass

        try:
            captcha_div = self.driver.find_element(By.ID, "captchaDiv")
        except NoSuchElementException:
            return False

        for seletor in seletores_interativos:
            for elemento in captcha_div.find_elements(By.CSS_SELECTOR, seletor):
                if elemento.is_displayed() and self._clicar_com_fallback(elemento):
                    return True

        self._clicar_com_fallback(captcha_div)

        try:
            widget_turnstile = self.driver.find_element(By.ID, "turnstileWidget")
        except NoSuchElementException:
            widget_turnstile = captcha_div

        try:
            dimensoes = widget_turnstile.size or {}
            largura = int(dimensoes.get("width") or 0)
            altura = int(dimensoes.get("height") or 0)
        except Exception:  # noqa: BLE001
            largura = 0
            altura = 0

        offsets_prioritarios = [
            (24, max(12, altura // 2 or 18)),
            (36, max(12, altura // 2 or 18)),
            (48, max(12, altura // 2 or 18)),
            (max(12, largura // 2), max(12, altura // 2 or 18)),
        ]
        for offset_x, offset_y in offsets_prioritarios:
            if self._clicar_com_offset(widget_turnstile, offset_x, offset_y):
                return True
        return False

    def consultar_chave(
        self,
        chave: str,
        tentativa_captcha_invalido: int = 0,
        cancelar_evento: threading.Event | None = None,
    ) -> bool:
        """Abre o site (ou reaproveita a sessão via "Nova Consulta"), envia a chave e
        aguarda a liberação da consulta, tentando resolver o captcha automaticamente."""
        try:
            botao_nova = self.driver.find_element(
                By.XPATH,
                "//*[contains(text(), 'Nova Consulta') or "
                "contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'nova consulta')]",
            )
            self.driver.execute_script("arguments[0].click();", botao_nova)
        except (NoSuchElementException, NoSuchWindowException, InvalidSessionIdException):
            self.driver.get(self.url_base)

        campo = self.wait.until(EC.presence_of_element_located((By.ID, "searchTxt")))
        self._preencher_campo_texto(campo, chave)
        time.sleep(0.3)

        if not _aguardar_execucao(cancelar_evento, self._pausar_evento):
            return False

        botao_busca = self.wait.until(EC.element_to_be_clickable((By.ID, "searchBtn")))
        self.driver.execute_script("arguments[0].click();", botao_busca)

        inicio = time.time()
        while time.time() - inicio < self.tempo_espera_captcha:
            if not _aguardar_execucao(cancelar_evento, self._pausar_evento):
                return False

            if self._elemento_visivel("optionsDiv"):
                return True

            if self._elemento_visivel("alertDiv"):
                mensagem = self._texto_alerta() or "Falha na consulta do Meu DANFE."
                texto_alerta = remover_acentos(mensagem)
                if "captcha invalido" in texto_alerta and tentativa_captcha_invalido < 1:
                    try:
                        self.driver.get(self.url_base)
                    except Exception:  # noqa: BLE001
                        pass
                    time.sleep(1)
                    return self.consultar_chave(chave, tentativa_captcha_invalido + 1, cancelar_evento=cancelar_evento)
                raise RuntimeError(mensagem)

            if self._elemento_visivel("captchaDiv"):
                self._tentar_clicar_captcha()

            time.sleep(1)

        raise TimeoutError(
            "Tempo esgotado aguardando a liberação da consulta no Meu DANFE. "
            "Se o captcha estiver visível, resolva-o manualmente e tente novamente."
        )

    def _aguardar_download(
        self,
        pasta_download: Path,
        extensao: str,
        cancelar_evento: threading.Event | None = None,
    ) -> Path | None:
        """Aguarda o arquivo aparecer e o tamanho estabilizar (sem `.crdownload` pendente)."""
        inicio = time.time()
        candidato_anterior: Path | None = None
        tamanho_anterior = -1

        while time.time() - inicio < self.tempo_download:
            if not _aguardar_execucao(cancelar_evento, self._pausar_evento):
                return None

            candidatos = sorted(pasta_download.glob(f"*{extensao}"))
            temporarios = list(pasta_download.glob("*.crdownload"))
            if candidatos:
                candidato = candidatos[-1]
                tamanho_atual = candidato.stat().st_size
                if candidato == candidato_anterior and tamanho_atual == tamanho_anterior and not temporarios:
                    return candidato
                candidato_anterior = candidato
                tamanho_anterior = tamanho_atual

            time.sleep(1)

        raise TimeoutError(f"Tempo esgotado aguardando o download do arquivo {extensao}.")

    def baixar_documentos(
        self,
        chave: str,
        cancelar_evento: threading.Event | None = None,
    ) -> DocumentoFiscalBaixado | None:
        """Baixa PDF e XML da consulta corrente para uma pasta temporária da chave."""
        pasta_chave = self.pasta_download_temporaria / chave
        pasta_chave.mkdir(parents=True, exist_ok=True)
        for arquivo in pasta_chave.iterdir():
            if arquivo.is_file():
                arquivo.unlink()
        self._configurar_pasta_download(pasta_chave)

        if not _aguardar_execucao(cancelar_evento, self._pausar_evento):
            return None
        botao_pdf = self.wait.until(EC.element_to_be_clickable((By.ID, "downloadDaBtn")))
        self.driver.execute_script("arguments[0].click();", botao_pdf)
        caminho_pdf = self._aguardar_download(pasta_chave, ".pdf", cancelar_evento)
        if caminho_pdf is None:
            return None

        if not _aguardar_execucao(cancelar_evento, self._pausar_evento):
            return None
        botao_xml = self.wait.until(EC.element_to_be_clickable((By.ID, "downloadXmlBtn")))
        self.driver.execute_script("arguments[0].click();", botao_xml)
        caminho_xml = self._aguardar_download(pasta_chave, ".xml", cancelar_evento)
        if caminho_xml is None:
            return None

        return DocumentoFiscalBaixado(pdf_bytes=caminho_pdf.read_bytes(), xml_bytes=caminho_xml.read_bytes())


@dataclass(slots=True)
class _ResultadoChave:
    chave: str
    caminho_planilha: Path
    situacao: str  # "sucesso" | "pulado" | "falha"
    erro: str = ""


def _processar_worker(
    registros_chunk: list[RegistroPlanilhaNFe],
    worker_id: int,
    settings: Settings,
    cancelar_evento: threading.Event | None,
    pausar_evento: threading.Event | None,
) -> list[_ResultadoChave]:
    """Processa uma fatia isolada da lista de chaves com seu próprio driver Chrome.

    Atraso escalonado `(worker_id-1)*6s` entre workers para evitar que várias
    instâncias disparem requisições simultâneas e acionem o mecanismo anti-bot do
    site (mesma mitigação do script original).
    """
    narrate("Worker %s: iniciando com %s chave(s) atribuída(s)...", worker_id, len(registros_chunk))
    resultados: list[_ResultadoChave] = []

    atraso = (worker_id - 1) * 6
    for _ in range(atraso):
        if not _aguardar_execucao(cancelar_evento, pausar_evento):
            return resultados
        time.sleep(1)

    with tempfile.TemporaryDirectory(prefix=f"meudanfe-worker{worker_id}-") as pasta_temp:
        automacao = MeudanfeChromeWorker(
            pasta_download_temporaria=Path(pasta_temp),
            tempo_espera_captcha=settings.nf_meudanfe_captcha_timeout_seconds,
            tempo_download=settings.nf_meudanfe_download_timeout_seconds,
            url_base=settings.nf_meudanfe_url,
            chrome_path=str(settings.nf_meudanfe_chrome_path) if settings.nf_meudanfe_chrome_path else None,
            pausar_evento=pausar_evento,
        )
        try:
            for indice, registro in enumerate(registros_chunk, start=1):
                if not _aguardar_execucao(cancelar_evento, pausar_evento):
                    break

                if arquivos_ja_existem(registro.pasta_destino, registro.chave):
                    resultados.append(_ResultadoChave(registro.chave, registro.caminho_planilha, "pulado"))
                    continue

                try:
                    if not automacao.consultar_chave(registro.chave, cancelar_evento=cancelar_evento):
                        break
                    documento = automacao.baixar_documentos(registro.chave, cancelar_evento=cancelar_evento)
                    if documento is None:
                        break
                    salvar_documentos_fiscais(registro.pasta_destino, registro.chave, documento)
                    resultados.append(_ResultadoChave(registro.chave, registro.caminho_planilha, "sucesso"))
                    narrate(
                        "Worker %s: chave %s baixada com sucesso (%s/%s).",
                        worker_id,
                        registro.chave,
                        indice,
                        len(registros_chunk),
                    )
                except Exception as erro:  # noqa: BLE001
                    resultados.append(_ResultadoChave(registro.chave, registro.caminho_planilha, "falha", str(erro)))
                    narrate_warning("Worker %s: falha ao baixar a chave %s: %s", worker_id, registro.chave, erro)
        finally:
            automacao.fechar()

    narrate("Worker %s: finalizado.", worker_id)
    return resultados


class MeudanfeBatchExtractor:
    """Orquestra a leitura das planilhas e o download em lote de XML/PDF via Meu DANFE.

    Gerencia seus próprios drivers Chrome (1 a `MAX_WORKERS_PERMITIDO` em paralelo) —
    não recebe nem depende de um `BrowserSession`/`BrowserContext` já aberto, ao
    contrário de `SigaContributorExtractor`/`NfceBatchExtractor`.
    """

    def __init__(self, settings: Settings, input_folder: Path, output_folder: Path) -> None:
        self.settings = settings
        self.input_folder = input_folder
        self.output_folder = output_folder

    def executar_lote(
        self,
        cancelar_evento: threading.Event | None = None,
        pausar_evento: threading.Event | None = None,
        on_planilha_concluida: Callable[[MeudanfeBatchResult], None] | None = None,
    ) -> list[MeudanfeBatchResult]:
        """Lê todas as planilhas NF-e da pasta configurada e baixa as chaves pendentes.

        `on_planilha_concluida`, se informado, é chamado a cada worker que termina
        (não só ao final do lote inteiro), uma vez para cada planilha cujo total foi
        atualizado pelos resultados daquele worker — um chunk de chaves não corresponde
        a uma única planilha, então uma mesma planilha pode disparar o callback mais de
        uma vez conforme diferentes workers terminam pedaços dela.

        As chaves que falharem na primeira passada ganham uma única retentativa
        automática ao final (mesma lógica de `processar_passada`, chamada de novo só
        com elas, após `nf_meudanfe_retry_wait_seconds`) — a maioria das falhas observadas em lotes
        reais não tem relação com o conteúdo do documento e parece ser instabilidade
        transitória do site sob volume alto, então espaçar a nova tentativa no tempo
        tende a recuperar boa parte delas sem intervenção do operador.
        """
        if not self.input_folder.exists():
            raise FileNotFoundError(f"A pasta {self.input_folder} não existe.")

        mapa_cod_empresa_cnpj = (
            load_cod_empresa_cnpj_base(self.settings.cod_empresa_cnpj_base_path)
            if self.settings.cod_empresa_cnpj_base_path
            else {}
        )

        narrate("Lendo planilhas de NF-e em %s...", self.input_folder)
        registros: list[RegistroPlanilhaNFe] = []
        for caminho_planilha in listar_planilhas_nfe(self.input_folder):
            try:
                registros.extend(
                    extrair_registros_planilha_nfe(
                        caminho_planilha, self.output_folder, self.input_folder, mapa_cod_empresa_cnpj
                    )
                )
            except Exception as exc:  # noqa: BLE001
                narrate_warning("Falha ao ler a planilha %s: %s", caminho_planilha.name, exc)

        resultados_por_planilha: dict[Path, MeudanfeBatchResult] = {
            caminho: MeudanfeBatchResult(caminho_planilha=caminho)
            for caminho in listar_planilhas_nfe(self.input_folder)
        }
        for registro in registros:
            resultados_por_planilha[registro.caminho_planilha].chaves_total += 1

        if not registros:
            narrate_warning("Nenhuma chave NF-e válida foi encontrada nas planilhas da pasta.")
            return list(resultados_por_planilha.values())

        narrate_success("%s chave(s) encontrada(s) em %s planilha(s).", len(registros), len(resultados_por_planilha))

        # Registro original por (planilha, chave), para reconstruir a lista de retentativa
        # a partir de quais chaves ficaram com situacao "falha" - _ResultadoChave não carrega
        # pasta_destino/linha_origem, só o suficiente para o resumo/log.
        registros_por_chave = {(r.caminho_planilha, r.chave): r for r in registros}
        # Último resultado conhecido de cada chave - uma retentativa bem-sucedida sobrescreve
        # a falha da primeira passada aqui, então os contadores finais refletem só o estado
        # definitivo (nunca soma duas vezes a mesma chave).
        resultado_final_por_chave: dict[tuple[Path, str], _ResultadoChave] = {}

        def recalcular_contadores_planilha(caminho: Path) -> None:
            resultado_planilha = resultados_por_planilha[caminho]
            resultado_planilha.chaves_baixadas = 0
            resultado_planilha.chaves_puladas = 0
            resultado_planilha.chaves_com_falha = 0
            for item in resultado_final_por_chave.values():
                if item.caminho_planilha != caminho:
                    continue
                if item.situacao == "sucesso":
                    resultado_planilha.chaves_baixadas += 1
                elif item.situacao == "pulado":
                    resultado_planilha.chaves_puladas += 1
                else:
                    resultado_planilha.chaves_com_falha += 1

        def processar_passada(pendentes: list[RegistroPlanilhaNFe], numero_passada: int) -> None:
            max_workers = max(1, min(MAX_WORKERS_PERMITIDO, self.settings.nf_meudanfe_max_workers))
            tamanho_chunk = math.ceil(len(pendentes) / max_workers)
            chunks = [pendentes[i : i + tamanho_chunk] for i in range(0, len(pendentes), tamanho_chunk)]

            narrate(
                "Iniciando %s worker(s) em paralelo para %s chave(s) (passada %s)...",
                len(chunks),
                len(pendentes),
                numero_passada,
            )

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futuros = [
                    executor.submit(_processar_worker, chunk, worker_id, self.settings, cancelar_evento, pausar_evento)
                    for worker_id, chunk in enumerate(chunks, start=1)
                ]
                for futuro in concurrent.futures.as_completed(futuros):
                    try:
                        resultados_worker = futuro.result()
                    except Exception as exc:  # noqa: BLE001
                        narrate_error("Um worker do modo NF-e falhou inesperadamente: %s", exc)
                        continue
                    planilhas_atualizadas: set[Path] = set()
                    for item in resultados_worker:
                        resultado_final_por_chave[(item.caminho_planilha, item.chave)] = item
                        planilhas_atualizadas.add(item.caminho_planilha)
                    for caminho in planilhas_atualizadas:
                        recalcular_contadores_planilha(caminho)
                        if on_planilha_concluida is not None:
                            on_planilha_concluida(resultados_por_planilha[caminho])

        processar_passada(registros, 1)

        cancelado = cancelar_evento is not None and cancelar_evento.is_set()
        falhas_1a_passada = [
            registros_por_chave[chave_id]
            for chave_id, item in resultado_final_por_chave.items()
            if item.situacao == "falha"
        ]
        if falhas_1a_passada and not cancelado:
            espera = max(0, self.settings.nf_meudanfe_retry_wait_seconds)
            narrate_warning(
                "%s chave(s) falharam na primeira passada. Nova tentativa automática em %ss...",
                len(falhas_1a_passada),
                espera,
            )
            if _aguardar_intervalo(espera, cancelar_evento, pausar_evento):
                processar_passada(falhas_1a_passada, 2)
            else:
                narrate_warning("Retentativa automática cancelada pelo usuário antes de começar.")

        for resultado in resultados_por_planilha.values():
            if resultado.chaves_total == 0:
                continue
            if resultado.status == "concluido":
                narrate_success(
                    "Planilha %s concluída: %s chave(s) baixadas, %s já existiam.",
                    resultado.caminho_planilha.name,
                    resultado.chaves_baixadas,
                    resultado.chaves_puladas,
                )
            else:
                narrate_warning(
                    "Planilha %s incompleta: %s baixadas, %s puladas, %s com falha (de %s).",
                    resultado.caminho_planilha.name,
                    resultado.chaves_baixadas,
                    resultado.chaves_puladas,
                    resultado.chaves_com_falha,
                    resultado.chaves_total,
                )

        chaves_com_falha = [
            (
                item.chave,
                item.caminho_planilha.name,
                str(
                    montar_pasta_destino_chave(
                        item.chave,
                        item.caminho_planilha,
                        self.output_folder,
                        self.input_folder,
                        mapa_cod_empresa_cnpj,
                        tipo_nota_do_nome_arquivo(item.caminho_planilha.name),
                    )
                ),
                item.erro,
            )
            for item in resultado_final_por_chave.values()
            if item.situacao == "falha"
        ]
        if chaves_com_falha:
            self._gravar_log_falhas(chaves_com_falha)

        return list(resultados_por_planilha.values())

    def _gravar_log_falhas(self, chaves_falhas: list[tuple[str, str, str, str]]) -> None:
        """Grava um arquivo enxuto só com as chaves que falharam, na pasta de destino."""
        caminho_log = self.output_folder / "chaves_falhas_meudanfe.log"
        linhas = ["Chaves que não obtiveram sucesso:"]
        for chave, planilha, pasta_destino, erro in chaves_falhas:
            linhas.append(f"- Chave {chave} | Planilha {planilha} | Pasta {pasta_destino} | Erro {erro}")
        caminho_log.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        narrate_warning("Log de chaves com falha gravado em %s", caminho_log)
