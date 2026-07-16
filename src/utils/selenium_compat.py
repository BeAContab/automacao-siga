from __future__ import annotations

"""Camada de compatibilidade que simplifica o uso do Selenium no projeto."""

import re
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from selenium.common.exceptions import (
    JavascriptException,
    NoSuchElementException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException as SeleniumTimeoutException,
    WebDriverException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

from src.config import Settings


Error = WebDriverException


class TimeoutError(WebDriverException):
    pass


ElementProvider = Callable[[], list[WebElement]]
NameMatcher = str | re.Pattern[str] | None


def _timeout_seconds(timeout_ms: int | None) -> float:
    if timeout_ms is None:
        return 30.0
    return max(timeout_ms / 1000, 0.1)


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _text_matches(value: str, matcher: NameMatcher, exact: bool = False) -> bool:
    normalized = _normalize_text(value)
    if matcher is None:
        return True
    if isinstance(matcher, re.Pattern):
        return matcher.search(normalized) is not None
    expected = _normalize_text(str(matcher))
    if exact:
        return normalized.casefold() == expected.casefold()
    return expected.casefold() in normalized.casefold()


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


def _key_value(key: str) -> str:
    mapping = {
        "Enter": Keys.ENTER,
        "Tab": Keys.TAB,
        "Escape": Keys.ESCAPE,
        "Esc": Keys.ESCAPE,
        "Backspace": Keys.BACKSPACE,
        "Delete": Keys.DELETE,
        "ArrowDown": Keys.ARROW_DOWN,
        "ArrowUp": Keys.ARROW_UP,
        "ArrowLeft": Keys.ARROW_LEFT,
        "ArrowRight": Keys.ARROW_RIGHT,
        "Home": Keys.HOME,
        "End": Keys.END,
        "PageDown": Keys.PAGE_DOWN,
        "PageUp": Keys.PAGE_UP,
    }
    return mapping.get(key, key)


class Download:
    """Representa um arquivo baixado pela automação e permite movê-lo para o destino final."""
    def __init__(self, path: Path) -> None:
        self.path = path
        self.suggested_filename = path.name

    def save_as(self, target: str) -> None:
        output_path = Path(target)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.resolve() == output_path.resolve():
            return
        if output_path.exists():
            output_path.unlink()
        shutil.move(str(self.path), str(output_path))
        self.path = output_path
        self.suggested_filename = output_path.name


class DownloadWaiter:
    """Context manager que aguarda um download terminar sem polling externo espalhado pelo código."""
    def __init__(self, page: Page, timeout_ms: int) -> None:
        self.page = page
        self.timeout_ms = timeout_ms
        self._snapshot: dict[Path, tuple[int, int]] = {}
        self._download: Download | None = None

    def __enter__(self) -> DownloadWaiter:
        self.page.context.configure_downloads()
        self._snapshot = self.page.context.download_snapshot()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            return False
        self._download = Download(
            self.page.context.wait_for_download(self._snapshot, self.timeout_ms)
        )
        return False

    @property
    def value(self) -> Download:
        if self._download is None:
            raise TimeoutError("O download nao foi concluido dentro do tempo esperado.")
        return self._download


class Keyboard:
    """Encapsula ações de teclado executadas na aba ativa."""
    def __init__(self, page: Page) -> None:
        self.page = page

    def press(self, key: str) -> None:
        self.page._switch()
        self.page.driver.switch_to.active_element.send_keys(_key_value(key))


class Mouse:
    """Encapsula cliques por coordenada quando o seletor não basta."""
    def __init__(self, page: Page) -> None:
        self.page = page

    def click(self, x_pos: int, y_pos: int) -> None:
        self.page._switch()
        script = """
        const element = document.elementFromPoint(arguments[0], arguments[1]);
        if (!element) {
            return false;
        }
        element.dispatchEvent(new MouseEvent('click', {
            bubbles: true,
            cancelable: true,
            clientX: arguments[0],
            clientY: arguments[1],
        }));
        return true;
        """
        clicked = self.page.driver.execute_script(script, x_pos, y_pos)
        if not clicked:
            ActionChains(self.page.driver).move_by_offset(x_pos, y_pos).click().perform()


class Locator:
    """Interface leve para localizar elementos, semelhante ao estilo do Playwright."""
    def __init__(
        self,
        page: Page,
        provider: ElementProvider,
        description: str,
        index: int | None = None,
    ) -> None:
        self.page = page
        self._provider = provider
        self.description = description
        self._index = index

    @property
    def first(self) -> Locator:
        return self.nth(0)

    def nth(self, index: int) -> Locator:
        return Locator(self.page, self._provider, f"{self.description}.nth({index})", index=index)

    def count(self) -> int:
        return len(self._elements())

    def inner_text(self, timeout: int | None = None) -> str:
        """Lê o texto visível do primeiro elemento encontrado."""
        element = self._element(timeout)
        text = element.text or element.get_attribute("innerText") or element.get_attribute("textContent") or ""
        return str(text)

    def click(self, timeout: int | None = None, force: bool = False) -> None:
        """Clica no elemento, forçando via JavaScript quando o clique normal falhar."""
        element = self._element(timeout)
        self.page._scroll_into_view(element)
        if force:
            self.page.driver.execute_script("arguments[0].click();", element)
            return
        try:
            element.click()
        except WebDriverException:
            self.page.driver.execute_script("arguments[0].click();", element)

    def fill(self, value: str, timeout: int | None = None) -> None:
        """Limpa o campo e preenche o valor informado."""
        element = self._element(timeout)
        self.page._scroll_into_view(element)
        element.click()
        try:
            element.clear()
        except WebDriverException:
            pass
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(Keys.BACKSPACE)
        if value:
            element.send_keys(value)

    def press(self, key: str) -> None:
        self._element().send_keys(_key_value(key))

    def is_visible(self) -> bool:
        try:
            return self._element().is_displayed()
        except WebDriverException:
            return False

    def is_enabled(self) -> bool:
        try:
            return self._element().is_enabled()
        except WebDriverException:
            return False

    def wait_for(self, state: str = "visible", timeout: int | None = None) -> None:
        deadline = time.time() + _timeout_seconds(timeout)
        while time.time() < deadline:
            elements = self._elements()
            if state in {"attached", "visible"}:
                for element in elements:
                    try:
                        if state == "attached" or element.is_displayed():
                            return
                    except WebDriverException:
                        continue
            elif state in {"hidden", "detached"}:
                if not elements or all(not element.is_displayed() for element in elements):
                    return
            time.sleep(0.2)
        raise TimeoutError(f"Timeout aguardando estado '{state}' em {self.description}.")

    def locator(self, selector: str) -> Locator:
        def provider() -> list[WebElement]:
            elements: list[WebElement] = []
            for root in self._elements():
                elements.extend(self.page._find_elements(selector, root=root))
            return elements

        return Locator(self.page, provider, f"{self.description} >> {selector}")

    def get_by_role(self, role: str, name: NameMatcher = None) -> Locator:
        return self._scoped_locator(lambda root: self.page._find_by_role(role, name, root=root), f"role={role}")

    def get_by_text(self, text: NameMatcher, exact: bool = False) -> Locator:
        return self._scoped_locator(lambda root: self.page._find_by_text(text, exact=exact, root=root), "text")

    def get_by_label(self, label: NameMatcher, exact: bool = False) -> Locator:
        return self._scoped_locator(lambda root: self.page._find_by_label(label, exact=exact, root=root), "label")

    def _scoped_locator(self, finder: Callable[[WebElement], list[WebElement]], description: str) -> Locator:
        def provider() -> list[WebElement]:
            elements: list[WebElement] = []
            for root in self._elements():
                elements.extend(finder(root))
            return elements

        return Locator(self.page, provider, f"{self.description} >> {description}")

    def _element(self, timeout: int | None = None) -> WebElement:
        if timeout is None:
            elements = self._elements()
            if not elements:
                raise NoSuchElementException(f"Nenhum elemento encontrado para {self.description}")
            return elements[0]

        deadline = time.time() + _timeout_seconds(timeout)
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                elements = self._elements()
                if elements:
                    return elements[0]
            except WebDriverException as exc:
                last_error = exc
            time.sleep(0.2)
        raise TimeoutError(f"Nenhum elemento encontrado para {self.description}") from last_error

    def _elements(self) -> list[WebElement]:
        self.page._switch()
        elements = [element for element in self._provider() if _is_attached(element)]
        if self._index is None:
            return elements
        if -len(elements) <= self._index < len(elements):
            return [elements[self._index]]
        return []


class Page:
    """Representa uma aba do navegador com operações de alto nível para a automação."""
    def __init__(self, context: BrowserContext, handle: str) -> None:
        self.context = context
        self.driver = context.driver
        self.handle = handle
        self.keyboard = Keyboard(self)
        self.mouse = Mouse(self)
        self._listeners: dict[str, list[Callable[..., None]]] = {}

    @property
    def url(self) -> str:
        self._switch()
        return self.driver.current_url

    def title(self) -> str:
        self._switch()
        return self.driver.title

    def is_closed(self) -> bool:
        return self.handle not in self.driver.window_handles

    def bring_to_front(self) -> None:
        self._switch()

    def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None) -> None:
        """Navega para uma URL e aguarda o estado mínimo da página quando solicitado."""
        self._switch()
        self.driver.set_page_load_timeout(_timeout_seconds(timeout))
        try:
            self.driver.get(url)
        except SeleniumTimeoutException as exc:
            raise TimeoutError(f"Timeout abrindo {url}") from exc
        if wait_until:
            self.wait_for_load_state(wait_until, timeout=timeout)

    def reload(self, wait_until: str | None = None, timeout: int | None = None) -> None:
        self._switch()
        try:
            self.driver.refresh()
        except SeleniumTimeoutException as exc:
            raise TimeoutError("Timeout recarregando a pagina") from exc
        if wait_until:
            self.wait_for_load_state(wait_until, timeout=timeout)

    def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        """Espera a página estabilizar em um estado de carregamento aceitável."""
        self._switch()
        try:
            WebDriverWait(self.driver, _timeout_seconds(timeout)).until(
                lambda driver: driver.execute_script("return document.readyState") in {"interactive", "complete"}
            )
        except SeleniumTimeoutException as exc:
            raise TimeoutError(f"Timeout aguardando load state '{state}'") from exc
        if state == "networkidle":
            time.sleep(1)

    def wait_for_timeout(self, timeout_ms: int) -> None:
        time.sleep(max(timeout_ms, 0) / 1000)

    def wait_for_url(self, matcher: str | re.Pattern[str], timeout: int | None = None) -> None:
        self._switch()

        def matches(driver: WebDriver) -> bool:
            current_url = driver.current_url
            if isinstance(matcher, re.Pattern):
                return matcher.search(current_url) is not None
            return str(matcher) in current_url

        try:
            WebDriverWait(self.driver, _timeout_seconds(timeout)).until(matches)
        except SeleniumTimeoutException as exc:
            raise TimeoutError("Timeout aguardando URL esperada") from exc

    def screenshot(self, path: str, full_page: bool = False) -> None:
        self._switch()
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.driver.save_screenshot(str(output_path))

    def content(self) -> str:
        self._switch()
        return self.driver.page_source

    def evaluate(self, script: str, arg: Any = None) -> Any:
        """Executa JavaScript para consultas ou ações que o Selenium não expressa bem."""
        self._switch()
        wrapped_script = f"return ({script})(arguments[0]);"
        try:
            return self.driver.execute_script(wrapped_script, arg)
        except JavascriptException:
            return self.driver.execute_script(script, arg)

    def expect_download(self, timeout: int) -> DownloadWaiter:
        return DownloadWaiter(self, timeout)

    def on(self, event_name: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event_name, []).append(callback)

    def remove_listener(self, event_name: str, callback: Callable[..., None]) -> None:
        listeners = self._listeners.get(event_name, [])
        if callback in listeners:
            listeners.remove(callback)

    def locator(self, selector: str) -> Locator:
        return Locator(self, lambda: self._find_elements(selector), selector)

    def get_by_role(self, role: str, name: NameMatcher = None) -> Locator:
        return Locator(self, lambda: self._find_by_role(role, name), f"role={role}")

    def get_by_text(self, text: NameMatcher, exact: bool = False) -> Locator:
        return Locator(self, lambda: self._find_by_text(text, exact=exact), "text")

    def get_by_label(self, label: NameMatcher, exact: bool = False) -> Locator:
        return Locator(self, lambda: self._find_by_label(label, exact=exact), "label")

    def get_by_placeholder(self, placeholder: NameMatcher) -> Locator:
        return Locator(
            self,
            lambda: [
                element
                for element in self._find_elements("input[placeholder], textarea[placeholder]")
                if _text_matches(element.get_attribute("placeholder") or "", placeholder)
            ],
            "placeholder",
        )

    def _switch(self) -> None:
        if self.handle not in self.driver.window_handles:
            raise NoSuchWindowException(f"A aba {self.handle} nao esta mais aberta.")
        if self.driver.current_window_handle != self.handle:
            self.driver.switch_to.window(self.handle)

    def _scroll_into_view(self, element: WebElement) -> None:
        self._switch()
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            element,
        )

    def _find_elements(self, selector: str, root: WebElement | None = None) -> list[WebElement]:
        self._switch()
        root_element: WebDriver | WebElement = root or self.driver
        if selector.startswith("xpath="):
            result = root_element.find_elements(By.XPATH, selector.removeprefix("xpath="))
        elif selector.startswith("text="):
            result = self._find_by_text_selector(selector.removeprefix("text="), root=root)
        else:
            result = root_element.find_elements(By.CSS_SELECTOR, selector)
        # O Selenium pode devolver None (em vez de lista vazia) quando o elemento raiz esta
        # no meio de uma re-renderizacao do DOM (comum em SPAs Angular como o SIGA). Sem essa
        # normalizacao, o TypeError resultante escapa dos "except Error" espalhados pelo
        # codigo, ja que TypeError nao e um WebDriverException.
        return result if result is not None else []

    def _find_by_text_selector(self, raw_text: str, root: WebElement | None = None) -> list[WebElement]:
        if raw_text.startswith("/") and raw_text.endswith("/i"):
            pattern = re.compile(raw_text[1:-2], re.IGNORECASE)
            return self._find_by_text(pattern, root=root)
        if raw_text.startswith("/") and raw_text.endswith("/"):
            pattern = re.compile(raw_text[1:-1])
            return self._find_by_text(pattern, root=root)
        return self._find_by_text(raw_text, root=root)

    def _find_by_text(
        self,
        text: NameMatcher,
        exact: bool = False,
        root: WebElement | None = None,
    ) -> list[WebElement]:
        candidates = self._descendants(root)
        matched = []
        for element in candidates:
            try:
                if element.tag_name.lower() in {"html", "body", "script", "style"}:
                    continue
                text_value = element.text or element.get_attribute("textContent") or ""
                if _text_matches(text_value, text, exact=exact):
                    matched.append(element)
            except WebDriverException:
                continue
        return _prefer_deepest(matched)

    def _find_by_role(
        self,
        role: str,
        name: NameMatcher = None,
        root: WebElement | None = None,
    ) -> list[WebElement]:
        selector = {
            "button": "button, input[type='button'], input[type='submit'], [role='button']",
            "link": "a, [role='link']",
            "tab": "[role='tab'], a",
            "row": "tr, [role='row'], .p-datatable-row",
            "searchbox": "input[type='search'], [role='searchbox']",
            "textbox": "input:not([type='hidden']), textarea, [role='textbox']",
        }.get(role, f"[role='{role}']")
        candidates = self._find_elements(selector, root=root)
        return [element for element in candidates if _text_matches(_accessible_name(element), name)]

    def _find_by_label(
        self,
        label: NameMatcher,
        exact: bool = False,
        root: WebElement | None = None,
    ) -> list[WebElement]:
        elements: list[WebElement] = []
        controls = self._find_elements(
            "input, textarea, select, button, [aria-label], [aria-labelledby]",
            root=root,
        )
        for control in controls:
            if _text_matches(_accessible_name(control), label, exact=exact):
                elements.append(control)
                continue
            control_id = control.get_attribute("id")
            if control_id:
                label_xpath = f".//label[@for={_xpath_literal(control_id)}]"
                labels = self.driver.find_elements(By.XPATH, label_xpath) if root is None else root.find_elements(By.XPATH, label_xpath)
                if any(_text_matches(item.text, label, exact=exact) for item in labels):
                    elements.append(control)
                    continue
            try:
                parent_label = control.find_element(By.XPATH, "ancestor::label[1]")
                if _text_matches(parent_label.text, label, exact=exact):
                    elements.append(control)
            except NoSuchElementException:
                pass
        return elements

    def _descendants(self, root: WebElement | None = None) -> list[WebElement]:
        if root is None:
            return self.driver.find_elements(By.CSS_SELECTOR, "*") or []
        return [root, *(root.find_elements(By.CSS_SELECTOR, "*") or [])]


class BrowserContext:
    """Agrupa o driver e os helpers de download usados durante a execução."""
    def __init__(self, driver: WebDriver, settings: Settings, owns_driver: bool) -> None:
        self.driver = driver
        self.settings = settings
        self.owns_driver = owns_driver
        self.download_dir = settings.output_dir / "_downloads"
        self.browser: Browser | None = None
        self.configure_downloads()

    @property
    def pages(self) -> list[Page]:
        return [Page(self, handle) for handle in self.driver.window_handles]

    def new_page(self) -> Page:
        """Abre uma nova aba e a devolve já associada ao contexto."""
        self.driver.switch_to.new_window("tab")
        return Page(self, self.driver.current_window_handle)

    def close(self) -> None:
        if self.owns_driver:
            self.driver.quit()
        else:
            service = getattr(self.driver, "service", None)
            if service is not None:
                with suppress(Exception):
                    service.stop()

    def configure_downloads(self) -> None:
        """Habilita o diretório padrão de downloads para arquivos baixados pelo navegador."""
        self.download_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.driver.execute_cdp_cmd(
                "Page.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(self.download_dir.resolve()),
                },
            )
        except WebDriverException:
            try:
                self.driver.execute_cdp_cmd(
                    "Browser.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": str(self.download_dir.resolve()),
                    },
                )
            except WebDriverException:
                pass

    def download_snapshot(self) -> dict[Path, tuple[int, int]]:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        return {
            path: (path.stat().st_size, int(path.stat().st_mtime_ns))
            for path in self.download_dir.iterdir()
            if path.is_file()
        }

    def wait_for_download(self, snapshot: dict[Path, tuple[int, int]], timeout_ms: int) -> Path:
        """Espera surgir um novo arquivo estável no diretório de downloads."""
        deadline = time.time() + _timeout_seconds(timeout_ms)
        while time.time() < deadline:
            for path in self.download_dir.iterdir():
                if not path.is_file() or _is_temporary_download(path):
                    continue
                stat = path.stat()
                state = (stat.st_size, int(stat.st_mtime_ns))
                if path not in snapshot or snapshot[path] != state:
                    if self._is_file_stable(path):
                        return path
            time.sleep(0.25)
        raise TimeoutError("O download nao foi concluido dentro do tempo esperado.")

    def _is_file_stable(self, path: Path) -> bool:
        try:
            first_size = path.stat().st_size
            time.sleep(0.35)
            return path.exists() and path.stat().st_size == first_size and not _is_temporary_download(path)
        except OSError:
            return False


class Browser:
    """Wrapper pequeno para permitir fechamento controlado da sessão compartilhada."""
    def __init__(self, driver: WebDriver, context: BrowserContext) -> None:
        self.driver = driver
        self._context = context

    @property
    def contexts(self) -> list[BrowserContext]:
        return [self._context]

    def close(self) -> None:
        with suppress(WebDriverException):
            self.driver.execute_cdp_cmd("Browser.close", {})
            return
        self.driver.quit()


def _is_attached(element: WebElement) -> bool:
    """Confirma se o elemento ainda pertence ao DOM antes de usá-lo."""
    try:
        element.is_enabled()
        return True
    except StaleElementReferenceException:
        return False
    except WebDriverException:
        return False


def _is_temporary_download(path: Path) -> bool:
    """Identifica arquivos ainda em progresso para evitar copiar downloads incompletos."""
    temporary_suffixes = {".crdownload", ".tmp", ".part"}
    return path.suffix.lower() in temporary_suffixes or path.name.endswith(".download")


def _accessible_name(element: WebElement) -> str:
    """Reconstrói um nome acessível aproximado a partir de atributos comuns."""
    values = [
        element.get_attribute("aria-label"),
        element.get_attribute("title"),
        element.get_attribute("alt"),
        element.get_attribute("value"),
        element.get_attribute("placeholder"),
        element.text,
        element.get_attribute("textContent"),
    ]
    return _normalize_text(" ".join(value for value in values if value))


def _prefer_deepest(elements: list[WebElement]) -> list[WebElement]:
    """Prefere os elementos mais específicos quando vários batem com o mesmo texto."""
    def child_match_count(element: WebElement) -> int:
        try:
            text = element.text or element.get_attribute("textContent") or ""
            return sum(1 for child in element.find_elements(By.CSS_SELECTOR, "*") if text and text in (child.text or ""))
        except WebDriverException:
            return 0

    return sorted(elements, key=lambda item: (child_match_count(item), len(item.text or "")))
