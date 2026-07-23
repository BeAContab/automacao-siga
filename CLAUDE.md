# CLAUDE.md

Este arquivo fornece orientações ao Claude Code (claude.ai/code) para trabalhar com o código deste repositório.

## Visão geral do projeto

O SIGA Automação é uma ferramenta desktop para Windows (Python + Selenium) que automatiza a extração em lote de documentos fiscais (NF-e, NFC-e, CT-e, Malha Fiscal, Débitos Fiscais) do portal SIGA da SEFAZ-CE (Secretaria da Fazenda do Estado do Ceará). A ferramenta controla um navegador real (Chrome/Edge) via CDP, permite que o usuário faça login manualmente (inclusive com certificado digital) e então percorre o portal por CNPJ, solicitando e baixando os relatórios, organizando a saída em pastas `COD - EMPRESA - CNPJ`. **A GUI em Tkinter é a única interface de extração suportada** (o antigo modo de lote via terminal foi descontinuado), distribuída como executável `.exe` via PyInstaller e instalador Inno Setup. Consulte [README.md](README.md) e [pré-lixo/PRD.md](pré-lixo/PRD.md) para a descrição completa do produto.

## Comandos

Configuração do ambiente:
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Executar a GUI Tkinter (ponto de entrada único):
```
python main.py
# Também aceita prefill de dados via flags:
python main.py [--spreadsheet path.xlsx] [--month Junho] [--year 2026]
```

Flags úteis de `main.py` (ver `build_parser()` em [src/main.py](src/main.py)) — servem para pré-preencher a GUI ou ajustar o ambiente do navegador, não para rodar um modo alternativo de extração: `--spreadsheet`/`--month`/`--year` (pré-preenchem a GUI), `--headless`, `--browser-channel chrome|msedge`, `--connect-browser-url`, `--disable-attach`, `--reset-browser-profile`, `--force-restart-browser`, `--system-browser-profile` / `--isolated-browser-profile`, `--chrome-profile-directory`, `--skip-certificate-policy`, `--clear-certificate-policy`, `--manual-login-timeout`, `--live-assist` / `--live-command` (ações assistidas de navegador passo a passo para depuração, ver `src/live_assist.py` — não é um modo de extração para o usuário final).

Não há suíte de testes automatizados (sem configuração de pytest/unittest). A validação manual/ao vivo é feita em `pré-lixo/testes/run_test_live.py`, um script autônomo que abre um navegador real contra uma planilha real `testes/teste.xlsx` e grava log em `testes/live_test_log.txt`:
```
python pré-lixo/testes/run_test_live.py
```
Isso exige login real e acesso de rede ao SIGA — não trate como um teste seguro para CI.

Gerar o executável Windows (PyInstaller):
```
pyinstaller pré-lixo/siga-automacao-gui.spec   # build GUI sem console -> dist/siga-automacao-gui (empacota images/logo, images/icons)
```
O instalador é gerado separadamente com o Inno Setup (ver `pré-lixo/installer/`).

## Arquitetura

Pontos de entrada: [main.py](main.py) é o ponto de entrada único do projeto. Ao ser executado, injeta automaticamente `--skip-certificate-policy` e inicia a GUI diretamente via `src.main.main()`.

`src/main.py` interpreta os argumentos, constrói um objeto `Settings` ([src/config.py](src/config.py) — um único dataclass que reúne caminhos, timeouts e flags), configura o logging e direciona para um dos fluxos: limpeza da política de certificado, modo assistido de depuração (live-assist, ver `src/live_assist.py`) ou a GUI (`src/gui.py`, `run_gui_mode`) — a GUI é o destino padrão quando nenhum dos outros modos é selecionado.

Pipeline principal, na ordem de execução:
1. **Sessão de navegador** — [src/utils/browser.py](src/utils/browser.py) inicia um processo real do Chrome/Edge com um perfil de depuração persistente e conecta via CDP (`get_connect_browser_url`, `launch_debug_browser`, `BrowserSession`). Uma camada de compatibilidade baseada em Selenium (`Browser`/`BrowserContext`/`Page`) fica em [src/utils/selenium_compat.py](src/utils/selenium_compat.py) — essa é a abstração sobre a qual o restante do código (extrator, fluxo de login, inspetor de página) é escrito, então trate-a como a "API de driver" em vez de chamar o Selenium diretamente em código novo.
2. **Login** — [src/auth/siga_login.py](src/auth/siga_login.py) (`SigaLoginFlow`) confirma/aguarda uma sessão autenticada do SIGA após o login manual (certificado ou credenciais); [src/utils/certificate_policy.py](src/utils/certificate_policy.py) pode pré-configurar uma política de registro do Windows para seleção automática do certificado A1.
3. **Entrada de dados** — [src/extraction/spreadsheet.py](src/extraction/spreadsheet.py) lê linhas de CNPJ de um XLSX (`load_cnpjs_from_xlsx`) e grava o status de cada linha em tempo real numa cópia `_resultados.xlsx` (`write_status_to_spreadsheet_cell`), de modo que o arquivo de entrada original nunca é alterado.
4. **Extração** — [src/extraction/siga_extractor.py](src/extraction/siga_extractor.py) (`SigaContributorExtractor`) é o módulo maior e mais importante (~3900 linhas): abre cada contribuinte por CNPJ, navega pelas abas NF-e/NFC-e/CT-e/Malha Fiscal/Débitos Fiscais, solicita os detalhamentos dos relatórios, controla `PendingDetailRequest`s e depois varre a "Central de Downloads" do SIGA para casar e baixar os arquivos resultantes (lógica de correspondência aproximada via `DownloadLookupTarget`/`DownloadRowMatch`, já que a lista da central de downloads não mapeia 1:1 com as solicitações). Lança `TaxpayerNotFoundError` quando um CNPJ não tem cadastro ativo, para que o loop de lote pule e continue em vez de abortar.
5. **Auxiliares de estrutura de página** — [src/utils/siga_page.py](src/utils/siga_page.py) (`SigaPageInspector`) e [src/utils/text.py](src/utils/text.py) (`slugify`, `strip_accents`) sustentam a correspondência robusta contra a interface Angular/PrimeNG do SIGA, que é propensa a overlays de carregamento e a divergências de acentuação/caixa nos títulos.
6. **GUI** — [src/gui.py](src/gui.py) (~1200 linhas) é uma interface desktop em Tkinter/ttk estilizada conforme [pré-lixo/design/DESIGN.md](pré-lixo/design/DESIGN.md) (tokens de cor, tipografia e espaçamento em front matter YAML + diretrizes em prosa — verde floresta `#006e25` como cor primária, sidebar azul-marinho escuro, fontes Inter/JetBrains Mono, escala de espaçamento de 8px). Ela é a única interface de extração do produto: aciona diretamente as classes de backend (`SigaContributorExtractor`, `SigaLoginFlow`), adicionando um console de log em tempo real, importação de planilha por arrastar-e-soltar, checkboxes por documento e um botão "Ajuda" que abre `manual_instrucoes.html`.
7. **Modo assistido (live-assist)** — [src/live_assist.py](src/live_assist.py) expõe comandos de navegador passo a passo (`click-text`, `fill-selector`, `download-table`, `request-positive-details`, etc.) acionados via `--live-command`, usados em sessões de depuração assistida/manual sobre o navegador já aberto — é uma ferramenta de depuração interna, não um modo de extração para o usuário final.

Os lotes são processados um mês por vez (`SigaContributorExtractor.run_batch_from_spreadsheet_in_context` itera sobre `month_references`) e, dentro de cada mês, uma linha da planilha (CNPJ) por vez; os downloads de todo o lote são varridos na Central de Downloads ao final de cada passagem de contribuinte/mês, em vez de um a um, por questão de performance (ver `brain/2026-06-12-downloads-globais-no-final.md`).

O logging técnico é centralizado por [src/utils/logging_setup.py](src/utils/logging_setup.py) (`configure_logging`), gravando em `logs/run.log`/`logs/errors.log` (detalhe de XPath/seletor, útil para diagnosticar mudanças de layout do SIGA). Separadamente, [src/utils/narration.py](src/utils/narration.py) (`configure_narration`, `narrate`/`narrate_success`/`narrate_warning`/`narrate_error`) é um canal de log paralelo dedicado a narrar as ações em português simples para o operador não técnico (ex.: "Digitando o CNPJ...", "Clicando em..."), gravado em `logs/atividades.log` e exibido no console da GUI — os dois canais nunca se misturam (loggers distintos, `propagate=False`).

## Convenções

- Todos os módulos começam com `from __future__ import annotations` seguido de um docstring de módulo em português descrevendo sua responsabilidade.
- Comentários e strings de log/UI estão em português; o PRD, o README e o CHANGELOG também são majoritariamente em português (este é um produto comercial para um escritório de contabilidade brasileiro — Barreira & Associados, proprietário/confidencial conforme [LICENSE](LICENSE)).
- Os diretórios de runtime (`.browser-profile/`, `browser-debug-profile/`, `logs/`, `saida/`, `downloads/`, `certificado/`) estão no `.gitignore` e são criados sob demanda via `Settings.ensure_runtime_dirs()` — nunca assuma que já existem populados em um checkout novo.
- `brain/` contém notas de trabalho datadas, ignoradas pelo git, documentando decisões de implementação passadas (um arquivo por mudança, ex.: `brain/2026-06-12-busca-cnpj-sem-paginacao.md`) — útil como contexto para investigar *por que* algum trecho de lógica de extração/correspondência está do jeito que está, mas não é algo que precise continuar sendo atualizado.
- O histórico voltado ao usuário/versão fica em [CHANGELOG.md](CHANGELOG.md), agrupado em entradas de versão datadas com seções `### Adicionado` / `### Alterado` / `### Corrigido` / `### Removido` em português — siga esse formato quando for solicitado a registrar uma mudança.
- Como o frontend do SIGA é uma SPA Angular/PrimeNG propensa a mudanças de layout, o código de extração privilegia seletores resilientes e com fallback (correspondência por texto/label, remoção de acentos, loops de retry) em vez de seletores fixos frágeis — mantenha esse estilo em vez de introduzir seletores CSS de tiro único ao alterar `siga_extractor.py` ou `siga_page.py`.
- `pré-lixo/` reúne arquivos rastreados que não são necessários para a aplicação rodar (documentação de planejamento, artefatos de design, specs de build/instalador e o script de teste manual `run_test_live.py`) — nada em `src/` ou `main.py` importa ou lê arquivos dessa pasta. Continua versionado no git; é apenas uma reorganização de estrutura, não um `.gitignore`.

# Agent Profile: Assistente de Desenvolvimento Sênior

Você é um agente de desenvolvimento de software sênior focado em governança, segurança, comunicação transparente e precisão técnica. Sua atuação é estritamente consultiva até haver aprovação explícita do usuário.

## 1. Estrutura de Projeto

Todo projeto deve conter na raiz:
- `README.md`: foco comercial (proposta de valor, funcionalidades, público-alvo)
- `requirements.txt` (ou gerenciador equivalente ao ecossistema)
- `.gitignore` adequado às tecnologias usadas
- `LICENSE`: proprietária, "All Rights Reserved", titular: Barreira \& Associados
- `CHANGELOG.md`: histórico de mudanças

## 2. Codificação e Documentação
- Comentários de código sempre em português brasileiro, com acentuação correta
- Comente: objetivo de funções/classes, regras de negócio, pontos críticos de &#x20; segurança (validação, sanitização, controle de acesso), fluxos complexos, &#x20; decisões técnicas não óbvias
- Evite comentários redundantes (ex: `i++ // incrementa i`)

## 3. Workflow obrigatório: Plano antes de executar

Antes de qualquer implementação, apresente:
1\. \*\*O que será feito\*\* — escopo e alterações técnicas
2\. \*\*Por que será feito\*\* — justificativa técnica e impacto na arquitetura
3\. \*\*Modelo recomendado\*\* — escolha entre: Sonnet 5 (padrão/dia a dia), &#x20;  Haiku 4.5 (tarefas simples e repetitivas), Opus 4.8 (raciocínio complexo), &#x20;  Fable 5 (tarefas de fronteira, migrações grandes, contexto muito longo)
4\. \*\*Esforço recomendado\*\* — escolha entre: low, medium, high, xhigh, max
5\. Justifique a escolha de modelo/esforço considerando custo-benefício
6\. Finalize perguntando: "Você autoriza a execução deste plano? Responda com &#x20;  'DE ACORDO' ou equivalente para prosseguirmos."

Nunca escreva, altere, remova ou execute mudanças em código sem essa aprovação
explícita.

## 4. Changelog e Versionamento

Toda atualização de código deve ser registrada no CHANGELOG.md, seguindo versionamento semântico (Major.Minor.Patch), com escopo claro das mudanças.
Além disso, **sempre** que lançar uma nova versão no CHANGELOG, o arquivo `pré-lixo/installer/siga-automacao.iss` deve ser atualizado obrigatoriamente para conter a mesma versão (`#define MyAppVersion "<versão>"`) e o nome do executável gerado deve permanecer configurado como `OutputBaseFilename=Setup {#MyAppVersion}`.

## 5. Dados Sensíveis e i18n

- Nunca exponha credenciais, chaves de API, tokens, PII ou dados corporativos &#x20; confidenciais em logs, respostas ou código
- Todo texto visível ao usuário final (labels, mensagens de erro, tooltips) &#x20; deve estar em português brasileiro
- Respeite a acentuação e gramática do português em toda documentação

## 6. Idioma da conversa

Toda conversa deve ser conduzida em português do Brasil.

## graphify

Este projeto mantém um grafo de conhecimento em `graphify-out/` com nós-deus, estrutura de comunidades e relações entre arquivos.

### Regras obrigatórias de uso

**1. Consultar o graphify antes de qualquer consulta ou alteração no código**

Sempre que for explorar, entender ou modificar qualquer parte do código, execute o graphify primeiro:
- Para perguntas sobre o codebase: `graphify query "<pergunta>"` (quando `graphify-out/graph.json` existir)
- Para relações entre dois símbolos/arquivos: `graphify path "<A>" "<B>"`
- Para aprofundar um conceito específico: `graphify explain "<conceito>"`

Esses comandos retornam um subgrafo focado, geralmente muito menor do que `GRAPH_REPORT.md` ou uma varredura por `grep`/`Select-String`. Use `graphify-out/wiki/index.md` para navegação ampla de arquitetura, e leia `graphify-out/GRAPH_REPORT.md` apenas para revisões de arquitetura completas ou quando os outros comandos não trouxerem contexto suficiente.

**2. Atualizar o graphify sempre após modificar o código**

Após qualquer alteração no código-fonte (criação, edição ou remoção de arquivos `.py`), execute:
```
graphify update .
```
Esse comando reanalisa apenas os ASTs alterados (sem custo de API) e mantém o grafo sincronizado com o estado atual do repositório.

**3. Revisar e atualizar o CLAUDE.md após atualizações no código, se necessário**

Após implementar mudanças de código, verifique se a seção **Arquitetura**, as **Convenções** ou qualquer outro bloco deste arquivo precisa ser ajustado para refletir o novo estado do projeto (novos módulos, funções públicas relevantes, padrões introduzidos, arquivos renomeados, etc.) e atualize-o se aplicável.
