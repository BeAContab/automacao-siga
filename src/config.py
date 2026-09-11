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
    # Timeout do download do navegador em si (expect_download), apos o clique no botao —
    # o arquivo XLSX ja pronto na Central de Downloads carrega rapido, entao 90s sobra.
    download_wait_timeout_ms: int = 90_000
    # Timeout de espera pelo SIGA GERAR o relatorio na Central de Downloads (processando ->
    # concluido) antes do clique — bem mais lento e variavel que o download em si; casos reais
    # chegaram a levar ate 12 minutos (ver comentario em _find_pending_download_matches).
    # Elevado de 240s para 600s apos um lote real de 22 solicitacoes (2 CNPJs x 5 abas fiscais)
    # onde a maioria das solicitacoes ainda nao tinha aparecido na Central passados os 240s —
    # fila do backend do SIGA sob carga (Central compartilhada com outros usuarios do
    # escritorio), nao um bug do lado cliente (ver ARQUIVOS/PASTA DE SAIDA/log.txt).
    download_generation_timeout_ms: int = 600_000
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
    # Retentativas ao SOLICITAR uma aba fiscal específica (Malha Fiscal, Débitos Fiscais,
    # NF-e, NFC-e, CT-e) dentro de um contribuinte já aberto — mesma classe de falha
    # transitória (timeout, overlay travado, lentidão momentânea) que já ganha 3 tentativas
    # na abertura do contribuinte (`_open_taxpayer_from_home`), mas que antes falhava
    # definitivamente na primeira tentativa quando ocorria aqui, minutos depois no fluxo.
    fiscal_tab_retry_count: int = 3
    fiscal_tab_retry_delay_ms: int = 2_000
    # Retentativas específicas para reautenticar e acessar a Central de Downloads ao final
    # do lote — o ponto mais caro de se perder de todo o fluxo, já que todas as solicitações
    # fiscais de todos os CNPJs já foram enviadas ao SIGA nesse momento (potencialmente
    # horas de trabalho). Caso real: sessão de 4h+ degradou perto do fim de um lote de 155
    # CNPJs e a página não renderizou nem após as 2 recargas padrão de
    # `stabilize_after_navigation`, perdendo a busca de 675 arquivos já prontos no SIGA.
    downloads_context_retry_count: int = 5
    downloads_context_retry_delay_ms: int = 5_000
    # Varreduras periodicas da Central de Downloads DURANTE o lote, em vez de so no final —
    # colhe arquivos assim que ficam prontos, espalhando a busca pelas horas que o lote
    # inteiro ja leva. Motivado por um lote real de 155 CNPJs/660 solicitacoes onde a unica
    # varredura final (com os 600s de `download_generation_timeout_ms`) so achou 95: os
    # pedidos sao enviados ao vivo ao longo do lote, mas ninguem ia buscar ate o fim. `0`
    # desliga os checkpoints e volta ao comportamento antigo (so varredura final).
    download_checkpoint_interval: int = 10
    # Pausa antes de cada checkpoint, dando um tempo minimo para o SIGA comecar a processar
    # as solicitacoes da ultima leva de empresas antes de olhar a Central.
    download_checkpoint_pause_ms: int = 30_000
    # Timeout de CADA checkpoint intermediario: curto e nao bloqueante — so colhe o que ja
    # estiver pronto agora. Nao e o prazo real de espera de um item: isso continua sendo
    # "quantos checkpoints faltam ate o fim do lote", mais a varredura final (que usa o
    # timeout completo de `download_generation_timeout_ms`, como ja acontece hoje).
    download_checkpoint_scan_timeout_ms: int = 10_000
    # Budget de cada tentativa de confirmar que a tabela/paginador da Central de Downloads
    # renderizou de verdade apos um `page.reload()`, antes de tentar ler/paginar. Corrige um
    # caso real: `reload(wait_until="domcontentloaded")` so espera o HTML inicial parsear, nao
    # o Angular buscar/renderizar a tabela — sem essa espera, o codigo tratava "componente
    # ainda nao montado" como "nao encontrado" silenciosamente, travando a varredura na
    # pagina 1 por 91 ciclos seguidos (~5min) ate a sessao do navegador cair.
    downloads_table_ready_timeout_ms: int = 8_000
    # Falhas consecutivas em confirmar o render da tabela (acima) antes de escalar para uma
    # recuperacao mais forte: reabrir a Central de Downloads do zero pelo menu, em vez de so
    # recarregar a mesma pagina de novo.
    downloads_render_retry_count: int = 3
    # Intervalo do aviso periodico ("ainda aguardando", com tempo decorrido) durante uma
    # espera longa na Central de Downloads — sem isso, o unico sinal visivel no console da
    # interface e uma linha identica se repetindo, indistinguivel de travamento real.
    download_wait_heartbeat_interval_ms: int = 60_000
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
    # Pasta de destino dos downloads (obrigatória, escolhida pelo usuário na interface,
    # mesmo padrão de "Pasta de saída"/"Pasta de saída dos XMLs" do SIGA/NFC-e) — cada
    # planilha grava em <destino>/downloads-meudanfe/<planilha>/{XML,PDF}.
    nf_meudanfe_output_folder: Path | None = None
    # 1 a 8 instâncias de Chrome em paralelo (undetected_chromedriver, uma por worker) —
    # teto igual ao do script original; mais paralelismo aumenta o risco de bloqueio
    # anti-bot (captcha do Cloudflare travando um worker), decisão consciente do usuário.
    nf_meudanfe_max_workers: int = 1
    nf_meudanfe_captcha_timeout_seconds: int = 180
    nf_meudanfe_download_timeout_seconds: int = 45

    # --- Interface (pywebview) ---
    # Habilita o DevTools do WebView2 (F12) na janela da interface. Só para
    # desenvolvimento — ativado por `--webui-debug` em `src/main.py`.
    webui_debug: bool = False

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
