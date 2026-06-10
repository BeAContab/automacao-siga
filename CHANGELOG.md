# Changelog

## [2026-06-10]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
  - src/live_assist.py
  - src/config.py
- Motivo: aumentar a tolerância do fluxo de download com timeout maior e uma nova tentativa automática, além de preservar a extensão real informada pelo arquivo baixado.
- Impacto: o processo ficou mais resiliente quando o SIGA demora para disparar o download e os arquivos finais passaram a manter a extensão coerente com o que o navegador informou.

## [2026-06-10]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
  - src/gui.py
  - src/main.py
  - src/utils/browser.py
  - src/utils/certificate_policy.py
  - src/utils/siga_page.py
  - src/live_assist.py
- Motivo: padronizar as mensagens exibidas no terminal e nos logs da execução para português, facilitando o acompanhamento do fluxo pelo usuário.
- Impacto: a saída da automação ficou mais clara para operação e diagnóstico, com logs e mensagens de console em português na maior parte do fluxo.

## [2026-06-10]

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o splitbutton do detalhamento podia ser localizado, mas o clique ainda podia atingir um elemento interno do texto em vez do botao principal.
- Impacto: o programa agora dispara o clique diretamente no `button` principal do `Baixar Tabela (XLSX)` por JavaScript quando o componente estiver pronto.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: a espera do detalhamento precisava reconhecer quando o splitbutton novo estava pronto de verdade, e nao apenas quando o texto aparecia.
- Impacto: o fluxo agora inspeciona o estado visual e funcional do botao `Baixar Tabela (XLSX)` antes de clicar, com log de progresso durante a espera.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o detalhamento novo usa um splitbutton cujo botao principal precisa ficar visivel e habilitado antes do clique apos a selecao do mes ou do subitem.
- Impacto: o fluxo agora aguarda o botao `p-element p-splitbutton-defaultbutton p-button p-component ng-star-inserted` ficar clicavel antes de solicitar o `Baixar Tabela (XLSX)`.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
  - src/gui.py
- Motivo: a busca da linha na Central de Downloads exigia correspondencia exata demais e podia falhar depois da varredura; a GUI ainda mascarava a falha original com um `NameError` no callback de erro.
- Impacto: a rotina de download agora aceita a melhor linha concluida compatível com os fragmentos da TELA/ABA, e a interface passa a exibir corretamente o erro real quando houver falha.

### Corrigido
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: a leitura do mes de referencia e o clique nos itens de detalhamento ficaram sensiveis ao layout novo do SIGA, especialmente antes do botao `Baixar Tabela (XLSX)`.
- Impacto: o fluxo agora usa fallback direto na tabela para localizar o mes e tenta clicar o relatorio e o botao XLSX com mais tolerancia ao DOM antes de desistir.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o fluxo de detalhamento passou a buscar explicitamente o botão `Baixar Tabela (XLSX)`, que agora representa a solicitação dos downloads assíncronos.
- Impacto: todos os detalhamentos passam a acionar o novo botão do layout atual, sem depender do rótulo antigo `Baixar Tabela`.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: a Central de Downloads passou a montar a lista completa de TELA/ABA, varrer todas as paginas uma unica vez por ciclo e so depois baixar em lote os arquivos encontrados.
- Impacto: reduz a repaginacao repetitiva por item, prioriza o registro mais recente por data/hora e continua gerando `.txt` para o que nao for localizado.

### Corrigido
- Arquivos:
  - main_gui.py
- Motivo: a entrada dedicada da GUI estava herdando a configuração automática de certificado na inicialização, o que podia travar a abertura da interface ao consultar o PowerShell.
- Impacto: a GUI passa a iniciar com `--skip-certificate-policy`, evitando bloqueio logo na abertura; a política continua disponível no fluxo de terminal quando necessário.

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: o fluxo de extração passou a preparar todas as solicitações de NF-e, NFC-e e CT-e antes de abrir a Central de Downloads.
- Impacto: o sistema agora solicita primeiro todos os arquivos de uma linha de contribuinte e só depois executa o download em lote, reduzindo alternâncias desnecessárias entre as abas do SIGA.

### Corrigido
- Arquivos:
  - src/utils/browser.py
  - siga-automacao-gui.spec
  - siga-automacao.spec
- Motivo: o executável empacotado falhava ao resolver dinamicamente `selenium.webdriver.chrome.webdriver` durante a abertura da GUI.
- Impacto: a criação do WebDriver passou a usar imports explícitos e os specs passaram a incluir os módulos do driver do Chrome e do Edge, reduzindo risco de erro no instalador e na build.

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: a barra de ações da GUI foi reorganizada para expor botões separados por documento, com marcação e desmarcação direta de NF-e, NFC-e e CT-e.
- Impacto: o usuario consegue controlar cada tipo de documento com mais clareza, sem depender apenas das seleções individuais da grade.

## [2026-06-09]

### Corrigido
- Arquivos:
  - LICENSE
- Motivo: ajuste da titularidade da licença proprietaria para `Barreira & Associados`, conforme a regra do projeto.
- Impacto: o repositório passa a exibir o proprietario correto no arquivo de licenciamento.

### Corrigido
- Arquivos:
  - src/utils/browser.py
  - siga-automacao-gui.spec
  - siga-automacao.spec
- Motivo: corrigido o erro de empacotamento que impedia a GUI de iniciar em outro computador por falha ao resolver `selenium.webdriver.chrome.options`.
- Impacto: o executavel passa a incluir os modulos de opcoes do Selenium e usa importacao direta para reduzir dependencia de carregamento dinamico.

## [2026-06-05]

### Corrigido
- Arquivos:
  - .gitignore
- Motivo: arquivos de log temporarios fora da pasta `logs/`, como `perf_after.log`, nao devem ficar no status do Git.
- Impacto: reduz ruido no repositorio e evita versionamento acidental de logs locais.

### Adicionado
- Arquivos:
  - main_gui.py
  - siga-automacao-gui.spec
- Motivo: criar uma build dedicada para a interface grafica, sem depender do parametro `--gui`.
- Impacto: o instalador pode distribuir um executavel especifico da GUI, mais simples para o usuario final.

### Corrigido
- Arquivos:
  - dist/siga-automacao-gui.exe
- Motivo: a build da GUI foi gerada com sucesso a partir do novo spec dedicado.
- Impacto: o instalador ja pode apontar para o binario grafico pronto para uso.

### Corrigido
- Arquivos:
  - installer/siga-automacao.iss
- Motivo: o instalador tentava criar atalho no desktop comum, o que pode falhar com `0x80070005` em instalacoes sem permissao elevada.
- Impacto: o atalho passa a ser criado no desktop do usuario (`{userdesktop}`), reduzindo risco de erro de acesso negado.

### Corrigido
- Arquivos:
  - installer/siga-automacao.iss
  - README.md
- Motivo: o instalador inicial apontava para o binario geral, mas a distribuicao desejada e a versao com GUI aberta por padrao.
- Impacto: os atalhos e a execucao pos-instalacao agora iniciam a interface grafica diretamente com `--gui`.

### Adicionado
- Arquivos:
  - installer/siga-automacao.iss
- Motivo: criar um script de instalador para o Inno Setup apontando para o executável do PyInstaller.
- Impacto: o projeto passa a ter um caminho padronizado para gerar um instalador Windows.

### Adicionado
- Arquivos:
  - dist/siga-automacao.exe
- Motivo: o executável Windows foi gerado com sucesso a partir do spec do PyInstaller.
- Impacto: a aplicação já pode ser distribuída e executada como `.exe` no Windows.

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: a interface grafica passou a permitir a escolha da pasta de saida antes da execucao.
- Impacto: o usuario agora controla onde os downloads finais serao gravados sem depender do diretorio padrao `saida/`.

### Documentação
- Arquivos:
  - README.md
  - brain/2026-06-05-escolha-pasta-downloads.md
- Motivo: registrar o novo fluxo da GUI e a decisao tecnica de sincronizar a pasta escolhida com `Settings.output_dir`.
- Impacto: melhora a rastreabilidade da alteracao e facilita a consulta futura.

### Documentação
- Arquivos:
  - README.md
- Motivo: documentar o comando de build do PyInstaller e o caminho do executavel gerado.
- Impacto: facilita a reproducao do pacote Windows em novas maquinas.

### Documentação
- Arquivos:
  - README.md
  - brain/2026-06-05-inno-setup-installer.md
- Motivo: registrar como compilar o instalador com o Inno Setup e onde o `.exe` final será produzido.
- Impacto: melhora a rastreabilidade e reduz dúvidas no empacotamento.

## [2026-06-03]

### Corrigido
- Arquivos:
  - src/main.py
  - src/gui.py
- Motivo: a interface grafica ainda estava abrindo o navegador cedo demais.
- Impacto: a GUI agora abre sozinha e o navegador só inicia ao clicar em `Iniciar navegador`.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: separar a abertura do navegador da execução e exigir login manual antes de processar.
- Impacto: o usuário passa a controlar a etapa de autenticação por um botão próprio na interface.

### Documentação
- Arquivos:
  - README.md
- Motivo: documentar o fluxo de `Iniciar navegador` seguido de login manual e depois `Executar`.
- Impacto: reduz confusão no uso da GUI.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/gui.py
- Motivo: alinhar melhor as colunas da lista de CNPJs na interface grafica.
- Impacto: a grade ficou mais legivel e estavel para selecao por linha.

## [2026-06-03]

### Adicionado
- Arquivos:
  - src/gui.py
- Motivo: criar uma interface gráfica para selecionar CNPJs e abas fiscais por item.
- Impacto: permite operação visual, sem depender do terminal para escolher o lote.

### Alterado
- Arquivos:
  - src/main.py
  - src/extraction/siga_extractor.py
- Motivo: integrar o novo modo `--gui` e permitir seleção de abas por CNPJ.
- Impacto: o backend passou a aceitar filtragem individual por contribuinte.

### Documentação
- Arquivos:
  - README.md
- Motivo: documentar o uso da interface gráfica.
- Impacto: facilita descoberta e adoção do novo modo.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: abrir automaticamente o menu lateral quando ele estiver recolhido, evitando bloqueios ao acessar Informacoes Fiscais e Downloads.
- Impacto: reduz TimeoutError de navegacao quando o menu lateral esta fechado.

## [2026-06-03]

### Alterado
- Arquivos:
  - src/extraction/siga_extractor.py
- Motivo: reduzir esperas fixas e tornar a varredura da Central de Downloads mais leve.
- Impacto: menor tempo gasto em cliques, abertura de seções e polling de arquivos assíncronos.

### Documentação
- Arquivos:
  - brain/2026-06-03-performance-download-optimization.md
- Motivo: registrar o plano de otimização e a medição antes/depois.
- Impacto: melhora a rastreabilidade da rodada de performance.

## [2026-06-03]

### Documentação
- Arquivos:
  - README.md
  - .gitignore
- Motivo: o projeto passou a documentar melhor a entrada `cnpj.xlsx`, a preservação de CNPJs com zero à esquerda e a referência de validação `testes.csv`.
- Impacto: reduz ambiguidade na configuração inicial e mantém a árvore local limpa sem ruídos desnecessários.

## [2026-06-03]

### Corrigido
- Arquivos:
  - src/extraction/spreadsheet.py
  - src/extraction/siga_extractor.py
- Motivo: a normalização de CNPJ estava removendo zeros à esquerda, o que quebrava casos como `02843131000166`.
- Impacto: a planilha agora preserva os 14 dígitos completos e a comparação com a fila do SIGA continua funcionando com a base `02843131`.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a extração de NFC-e/Emissor em Maio de 2026 passou a reencontrar a linha visível da fila de downloads e a clicar no item vivo do DOM antes de salvar o arquivo.
- Impacto: o CSV final `Informacoes Fiscais - NFC-e - Emissor - Detalhamento Maio de 2026.csv` agora fica byte a byte igual ao `testes.csv` de referência para o CNPJ 10484384000119.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a seleção do download assíncrono deixou de aceitar filas antigas como fallback quando a solicitação nova ainda não apareceu.
- Impacto: reduz a chance de baixar um arquivo velho e salvar com o nome da execução atual.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a NFC-e deixou de acrescentar o sufixo `Autorizadas` no nome solicitado para download assíncrono.
- Impacto: o relatório passa a ser procurado e salvo como `Informacoes Fiscais - NFC-e - Emissor - Detalhamento Maio de 2026`, conforme pedido.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: os downloads assíncronos voltaram a ser renomeados pelo padrão da TELA/ABA solicitada.
- Impacto: o nome final do arquivo passa a refletir a consulta esperada pela automação, independentemente do nome sugerido pelo navegador.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a abertura do mês de referência passou a tentar novamente quando a lista ainda não terminou de carregar.
- Impacto: reduz falhas intermitentes ao trocar de seção e procurar o mês `Maio` antes do DOM estabilizar.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: os downloads assíncronos passaram a ser salvos com o `suggested_filename` original do SIGA em vez de um nome renomeado pela automação.
- Impacto: reduz o mascaramento de arquivos errados com nomes “bonitos” e facilita a auditoria do que foi realmente baixado.

## [2026-06-03]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o matcher da Central de Downloads passou a exigir a correspondencia completa da linha, incluindo o recorte final `Interna`, `Interestadual` ou `Externa`.
- Impacto: evita baixar um arquivo valido, mas de outro recorte, com nome renomeado de forma incorreta.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a leitura das métricas anuais ganhou tentativas curtas com espera entre elas antes de concluir que o campo não apareceu.
- Impacto: reduz erro por carregamento incompleto da página em seções como NFC-e/Destinatario.

## [2026-06-03]

### Removido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o fallback de CNPJ BASE zerado foi removido da Central de Downloads.
- Impacto: a automação agora baixa apenas quando encontra o CNPJ correto da planilha; caso contrário, gera o TXT de indisponibilidade.

## [2026-06-03]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o matcher da Central de Downloads passou a varrer as células da linha para localizar a TELA/ABA completa, validar CNPJ na mesma linha e aguardar 5 segundos quando o status ainda estiver em processamento.
- Impacto: reduz falso negativo quando a linha existe na tabela, mas a posição das colunas ou a formatação do CNPJ variam.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: o clique no item da Central de Downloads podia falhar quando o `Locator` da linha ficava inválido após a atualização do DOM.
- Impacto: a automação agora reencontra a linha pelo texto da `TELA/ABA` antes de clicar no download, reduzindo `NoSuchElementException`.

## [2026-06-02]

### Alterado
- Arquivos:
  - src/extraction/spreadsheet.py
  - src/main.py
  - src/extraction/siga_extractor.py
  - README.md

- Motivo:
  Migração da entrada da automação de CGF para CNPJ, incluindo leitura da planilha `cnpj.xlsx`, mensagens do terminal e documentação de uso.

- Impacto:
  O fluxo passa a aceitar planilhas com coluna `cnpj` e exibe CNPJ nas mensagens visíveis ao usuário.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a busca na Central de Downloads rejeitava arquivos já concluídos quando a linha não era mais recente que a solicitação atual, mesmo com a TELA/ABA correta disponível.
- Impacto: o matcher agora aceita a última linha concluída compatível com a TELA/ABA quando nenhuma linha nova aparece, reduzindo avisos falsos de indisponibilidade.

## [2026-06-02]

### Alterado
- Arquivo: src/extraction/siga_extractor.py
- Motivo: alinhar o fluxo fiscal ao `fluxo.docx`, padronizando nomes de resumos, liberando a abertura do mês com base em quantidade positiva e mantendo o detalhamento por reportes do mês.
- Impacto: a automação agora segue melhor a regra operacional descrita para NF-e, NFC-e e CT-e e reduz cliques desnecessários.

### Alterado
- Arquivo: src/live_assist.py
- Motivo: espelhar no modo assistido o mesmo critério de quantidade positiva usado pela extração principal.
- Impacto: os comandos manuais passam a relatar o fluxo com mensagens coerentes com a lógica atual.

### Documentação
- Arquivo: brain/2026-06-02-fluxo-docx.md
- Motivo: registrar a decisão técnica adotada para aplicar as mudanças do documento de fluxo.
- Impacto: mantém rastreabilidade da alteração nesta sessão.

## [2026-06-02]

### Documentação
- Arquivos:
  - src/main.py
  - src/auth/siga_login.py
  - src/config.py
  - src/extraction/spreadsheet.py
  - src/extraction/siga_extractor.py
  - src/live_assist.py
  - src/utils/browser.py
  - src/utils/certificate_policy.py
  - src/utils/logging_setup.py
  - src/utils/selenium_compat.py
  - src/utils/siga_page.py
  - src/utils/text.py

- Motivo:
  Inserção de comentários e docstrings em português para explicar fluxo de terminal, autenticação, leitura de planilha, extração fiscal, modo assistido e utilitários de navegação.

- Impacto:
  O código ficou mais fácil de manter e revisar, principalmente nas partes com regras de negócio e fallback de automação.

## [2026-06-02]

### Removido
- Arquivos e pastas:
  - browser-debug-profile/
  - .browser-profile/
  - build/
  - dist/
  - logs/
  - saida/
  - teste-navegador/
  - main.spec
  - cgf.xlsx
  - xpath-download-assincrono.xlsx

- Motivo:
  Limpeza de artefatos locais gerados por navegador, empacotamento, logs e planilhas soltas que não fazem parte do código-fonte.

- Impacto:
  Reduz ruído no repositório, evita versionamento de dados temporários e deixa o projeto mais previsível para manutenção.

### Documentação
- Arquivo: brain/2026-06-02-limpeza-repositorio.md
- Motivo:
  Registro da decisão de limpeza e dos itens removidos.
- Impacto:
  Mantém rastreabilidade do que foi tratado nesta sessão.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: na lista de contribuintes do SIGA, a célula que corresponde ao CGF é a segunda coluna (`td[2]` no XPath), e ela é o alvo mais consistente para abrir o detalhe.
- Impacto: a automação passa a clicar prioritariamente na célula do CGF da linha encontrada, reduzindo o risco de acionar outros elementos da tabela.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a abertura do contribuinte podia clicar no último alvo da linha, o que acabava acionando o link errado em vez de entrar no detalhe.
- Impacto: a automação passa a priorizar o primeiro `td` da linha encontrada pelo CGF antes de tentar o clique genérico na linha.

## [2026-06-02]

### Segurança
- Arquivo: .gitignore
- Motivo: diretórios locais de build (`build/` e `dist/`) estavam aparecendo no status do Git e não devem ser versionados.
- Impacto: reduz ruído no controle de versão e evita o envio acidental de artefatos gerados localmente.

## [2026-06-02]

### Corrigido
- Arquivo: src/extraction/spreadsheet.py
- Motivo: a planilha podia fornecer CGF com zero à esquerda, o que fazia a busca do contribuinte falhar no SIGA.
- Impacto: o CGF agora é normalizado sem zeros à esquerda ao ser lido da planilha, permitindo a pesquisa correta com valores como `065579828` -> `65579828`.

## [2026-06-01]

### Corrigido
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a abertura do contribuinte podia travar após a pesquisa do CGF quando a tabela ainda estava renderizando ou quando a varredura de texto via Selenium ficava lenta.
- Impacto: a automação passa a aguardar o resultado filtrado, tenta abrir o detalhamento com seletores mais específicos, usa fallback por DOM e só prossegue após confirmar a tela de detalhes.
- Arquivo: src/extraction/siga_extractor.py
- Motivo: a lista de contribuintes podia terminar de carregar somente depois do timeout inicial, interrompendo o fluxo antes da pesquisa do CGF.
- Impacto: a espera inicial pela lista virou permissiva, o ciclo de pesquisa/abertura ganhou retentativas e a validação forte passou a ocorrer após o envio do CGF.

### Adicionado
- Arquivo: LICENSE
- Motivo: inclusão da licença proprietária privada obrigatória do projeto.
- Impacto: formaliza que o projeto é privado e possui todos os direitos reservados.

### Dependências
- Arquivo: requirements.txt
- Motivo: instalação do `pyinstaller==6.20.0` para permitir empacotamento da automação em executável.
- Impacto: o ambiente Python passa a ter a ferramenta de build necessária para gerar distribuições locais do projeto.

### Corrigido
- Arquivo: siga-automacao.spec
- Motivo: o executável `onefile` falhava ao iniciar com `ModuleNotFoundError` para `selenium.webdriver.common.action_chains`.
- Impacto: inclusão de `hiddenimports` do Selenium no build, permitindo inicialização correta do executável empacotado.

### Segurança
- Arquivo: .gitignore
- Motivo: inclusão do padrão `*.sqlite-journal` na lista de bancos locais ignorados.
- Impacto: reduz risco de versionar arquivos auxiliares de banco local.

### Documentação
- Arquivo: brain/2026-06-01-abertura-contribuinte.md
- Motivo: registro da decisão técnica aplicada ao fluxo de abertura do contribuinte.
- Impacto: mantém rastreabilidade do diagnóstico e da correção.
- Arquivo: brain/2026-06-01-pyinstaller.md
- Motivo: registro da instalação do PyInstaller como ferramenta de empacotamento local.
- Impacto: mantém rastreabilidade da decisão de dependência.
- Arquivo: brain/2026-06-01-pyinstaller-onefile-fix.md
- Motivo: registro da correção aplicada ao empacotamento `onefile` com `hiddenimports`.
- Impacto: mantém histórico técnico do ajuste necessário para execução do `.exe`.

## 1.1.0 - 2026-05-27

- Migrada a automacao principal de Playwright para Selenium WebDriver.
- Mantido o fluxo de login manual no mesmo Chrome/Edge com CDP ativo, agora por `debuggerAddress` do Selenium.
- Adicionada uma camada interna de compatibilidade para preservar seletores, abas, comandos assistidos e captura deterministica de downloads.
- Alterada a ordem do fluxo: o Selenium passa a ser anexado somente depois do login manual, evitando controle WebDriver durante certificado/recaptcha.
- Corrigido o clique de download na central assíncrona do SIGA para acionar a última célula da linha, onde o texto `Download` dispara o arquivo.
- A busca de downloads assíncronos agora valida o CNPJ do contribuinte na linha da central, permitindo reaproveitar arquivos ainda válidos do mesmo contribuinte e evitando escolher histórico de outro contribuinte quando o texto da tela é parecido.
- Otimizada a extração de métricas por rótulo para evitar varreduras lentas de texto no Selenium.
- Substituida a dependencia `playwright` por `selenium==4.44.0`.

## 1.0.9 - 2026-05-27

- Adicionado fallback para ambientes que bloqueiam escrita em `HKCU\Software\Policies`: o programa agora gera `logs/chrome-certificate-policy.reg` com a politica pronta para aplicacao manual.
- Ajustado o fluxo para informar no terminal quando a politica nao foi gravada automaticamente por falta de permissao.

## 1.0.8 - 2026-05-27

- Adicionada configuracao automatica da politica `AutoSelectCertificateForUrls` no Registro do Windows para Chrome/Edge, usando o certificado de cliente instalado no usuario atual.
- Incluidos os argumentos `--skip-certificate-policy` e `--clear-certificate-policy` para controlar ou remover a politica local quando necessario.
- Documentado o fluxo de selecao automatica de certificado digital para os dominios `sso.sefaz.ce.gov.br` e `siga.sefaz.ce.gov.br`.

## 1.0.7 - 2026-05-27

- Alterado o padrao de abertura do Chrome para usar novamente um perfil dedicado de automacao com `--user-data-dir`, evitando bloqueios do Chrome ao tentar ativar CDP no perfil normal do usuario.
- Adicionado o argumento `--system-browser-profile` para tentativa explicita de uso do perfil normal, quando necessario.
- Atualizada a documentacao para esclarecer que a selecao de certificado digital no Windows depende dos certificados instalados no repositario do usuario do Windows.

## 1.0.6 - 2026-05-27

- Adicionado fallback automatico na abertura do navegador: quando o CDP em `127.0.0.1:9222` nao sobe na primeira tentativa, o fluxo encerra processos antigos do navegador e tenta iniciar novamente uma vez.
- Mantida a opcao manual `--force-restart-browser`; o fallback agora reduz falhas mesmo quando a flag nao e informada.

## 1.0.5 - 2026-05-27

- Adicionado o argumento `--force-restart-browser` para encerrar os processos do navegador (`chrome.exe` ou `msedge.exe`) antes de abrir uma nova sessao com CDP.
- O fluxo de abertura agora pode limpar processos antigos que bloqueavam a porta de depuracao e causavam falha de conexao em `http://127.0.0.1:9222`.

## 1.0.4 - 2026-05-27

- Alterada a abertura manual do Chrome para usar o perfil normal do usuario por padrao, permitindo que a opcao `Seu certificado digital` liste os certificados instalados no navegador/Windows.
- Adicionado o argumento `--isolated-browser-profile` para voltar ao perfil isolado da automacao quando necessario.
- Adicionado o argumento `--chrome-profile-directory` para escolher explicitamente um perfil do Chrome, como `Default` ou `Profile 1`.
- Documentado o cuidado de fechar o Chrome antes de iniciar o fluxo, evitando que um processo antigo sem CDP bloqueie o anexo da automacao.
- Incluidos perfis locais de navegador no `.gitignore`.

## 1.0.3 - 2026-05-27

- Removida a integracao com Gemini e seus fallbacks visuais.
- Removida a dependencia `google-genai` do `requirements.txt`.
- Removido o comando `click-visual` do `live-assist`, mantendo apenas comandos deterministas por texto, seletor, label, coordenadas e fluxos especificos.

## 1.0.2 - 2026-05-27

- Removido o anexo automatico do certificado A1 via Playwright (`client_certificates`), que criava um novo contexto CDP e podia abrir uma segunda janela do navegador.
- O `BrowserSession` agora reaproveita o contexto existente do Chrome conectado em `9222`, mantendo uma unica instancia no fluxo principal.

## 1.0.1 - 2026-05-27

- Corrigido o fluxo interativo para definir explicitamente `connect_browser_url` antes de abrir o navegador, garantindo anexo por CDP no mesmo processo.
- Evitada a abertura de segunda instancia no fluxo principal de terminal ao reaproveitar o navegador iniciado em `9222`.

## 1.0.0 - 2026-05-27

- Removida a GUI do fluxo principal e substituida por um assistente interativo via terminal.
- A execucao padrao agora solicita mes, planilha, abre o navegador para login manual e executa a extracao no mesmo contexto autenticado.
- Corrigida a perda de sessao entre login manual e extracao ao manter o lote dentro da mesma `BrowserSession`.
- Mantido o modo `live-assist` para diagnosticos assistidos.
- Reforcado o fluxo de erro para registrar falhas fatais em `logs/errors.log` por meio do logging central.

## 0.2.17 - 2026-05-26

- Corrigida a confirmacao de login manual na GUI para validar a sessao autenticada considerando os contextos ativos do browser conectado via CDP.
- Ajustado o fluxo do botao `Confirmar Login` para passar a referencia do browser conectado ao validador, reduzindo falso negativo apos login ja concluido.

## 0.2.16 - 2026-05-26

- Corrigido o fluxo da GUI no botao `Iniciar Navegador`: o navegador volta a abrir mesmo quando ha certificado A1 configurado.
- Mantida a protecao contra duplicidade: se ja existir navegador respondendo em CDP, o processo nao abre uma nova instancia.

## 0.2.15 - 2026-05-26

- Ajustada a selecao da linha na aba `Downloads` para priorizar sempre a solicitacao mais recente por data/hora (`Solicitado em`) ao baixar detalhamentos.
- Mantida a busca por correspondencia exata de `TELA/ABA` e, quando necessario, fallback `fuzzy`, ambos agora com criterio de desempate por recencia.
- Preservado o fallback de captura direta do arquivo quando a URL assinada nao e retornada, com logs mais claros indicando a estrategia escolhida.

## 0.2.14 - 2026-05-26

- Corrigida a etapa de download na central `Downloads` com busca mais tolerante da coluna `TELA/ABA`, evitando dependencia de correspondencia textual estrita (ex.: variacoes com/sem `Autorizadas`).
- Adicionado fallback para captura direta do arquivo via navegador quando a URL assinada nao e retornada no evento de resposta.
- Ajustado o clique da acao de download da linha para usar seletores resilientes de botao/link, reduzindo falhas por coluna fixa.
- Incluidos logs explicitos da estrategia de match usada (`exact` ou `fuzzy`) e do modo de salvamento (`signed URL` ou captura direta).

## 0.2.13 - 2026-05-26

- Generalizado o extrator fiscal para processar duas abas de `Informacoes Fiscais`: `NF-e` e `NFC-e`.
- Na `NFC-e`, o resumo de `Emissor` e `Destinatario` agora so e baixado quando os totais anuais de quantidade e valor sao positivos.
- Na `NFC-e`, o detalhamento agora segue o fluxo validado em `live-assist`: abrir o mes apenas quando houver valores positivos, solicitar `Autorizadas`, ir a `Downloads`, localizar pela coluna `TELA/ABA` e salvar o CSV.
- Os arquivos passaram a ser separados por pasta de aba fiscal, por exemplo `saida/<cgf>/<mes>/NF-e/` e `saida/<cgf>/<mes>/NFC-e/`.
- Tornado mais robusto o clique dos radios `Emissor` e `Destinatario` com `force=True` via `XPath`, melhorando a troca de perfil em telas como `NFC-e`.
- A localizacao de solicitacoes em `Downloads` passou a comparar `TELA/ABA` de forma normalizada, sem depender de acentuacao exata.

## 0.2.12 - 2026-05-26

- Substituidos por `XPath` os cliques mais instaveis do fluxo fiscal: campo de busca, linha do contribuinte, menu `Informacoes Fiscais`, radios `Emissor`/`Destinatario`, linha do mes, linhas `Interna`/`Interestadual`/`Externa`, botao de detalhamento `Baixar Tabela` e menu `Downloads`.
- Adicionados logs explicitos para registrar quando um clique critico foi executado via `XPath`, facilitando diagnostico no `run.log`.

## 0.2.11 - 2026-05-26

- Ajustada a regra da automacao para so abrir o mes de referencia quando a linha do mes tiver `QTD > 0` e `VALOR R$ > 0`.
- Removido o fallback que solicitava detalhamentos apenas por texto visivel, impedindo downloads indevidos de linhas zeradas como `Externa`.
- Tornado estavel o clique entre `Emissor` e `Destinatario` usando os radios reais da pagina fiscal, evitando desvio para `Manifestacao Destinatario`.
- Adicionadas notificacoes finais mais claras na GUI para diferenciar conclusao com downloads, conclusao sem dados e erro.
- Ao final do processo na GUI, o navegador agora e encerrado automaticamente; o mesmo comportamento foi exposto no `live-assist` com novos comandos para validar mes positivo, detalhamentos positivos e fechamento do navegador.

## 0.2.10 - 2026-05-26

- Reordenado o fluxo de extracao para seguir a sequencia operacional definida: baixar tabelas de `Emissor`/`Destinatario`, solicitar todos os detalhamentos e so depois entrar em `Downloads` para baixar os arquivos solicitados.
- Ajustado o processamento para baixar os detalhamentos pendentes em lote na aba `Downloads` e retornar para o fluxo principal.

## 0.2.9 - 2026-05-26

- Corrigido o log de erro da GUI para registrar o traceback real da excecao em `errors.log`, evitando entradas sem pilha (`NoneType: None`).

## 0.2.8 - 2026-05-26

- Adicionado tratamento global de excecoes nao tratadas (`sys.excepthook` e `threading.excepthook`) para registrar erros com stack trace em log.
- Envolvido o fluxo principal em captura final com `logging.exception`, garantindo registro no `errors.log` para falhas fatais.

## 0.2.7 - 2026-05-26

- Automatizado o fluxo completo do detalhamento assíncrono: clique em `Downloads`, localizacao da linha correta pela coluna `TELA/ABA`, captura da URL assinada e salvamento do CSV.
- Os arquivos de detalhamento agora passam a ser salvos com base no texto da coluna `TELA/ABA`, sanitizando apenas caracteres invalidos para Windows.

# 0.2.7 - 2026-06-02

- Corrigida a chamada de captura de download na central para repassar `tela_aba` ao clicar na linha encontrada.
- Motivo: o fluxo havia avançado até a seleção da linha, mas quebrava com `TypeError` por desencontro entre assinatura e chamada em `src/extraction/siga_extractor.py`.

## 0.2.6 - 2026-05-26

- Ajustado o fluxo de detalhamento fiscal para processar todos os tipos com `QTD > 0` e `VALOR R$ > 0`, em vez de apenas um unico tipo por perfil.
- Diferenciado o `Baixar Tabela` da secao `2. Detalhamento ...` do `Baixar Tabela` da secao `1. Indicadores por Mes`.
- Mantido o download do detalhamento pela aba `Downloads`, conforme o comportamento real observado no SIGA.

## 0.2.5 - 2026-05-26

- Alterado o fluxo para exigir a definicao do mes de referencia antes de iniciar o navegador na GUI.
- Reordenado o fluxo de `Informacoes Fiscais` para baixar primeiro as tabelas de `Emissor` e `Destinatario` e somente depois abrir o mes selecionado para o detalhamento.

## 0.2.4 - 2026-05-26

- Corrigido o fluxo de download para manter nome final deterministico em CSV mesmo quando o SIGA retorna nome tecnico (UUID/sem extensao).
- Adicionado comando `download-table` no modo assistido para capturar o download com `expect_download` e salvar com nome controlado em `saida/live-assist/`.
- Incluidos logs de diagnostico do nome sugerido pelo navegador versus caminho final salvo.

## 0.2.3 - 2026-05-26

- Adicionado modo assistido para abrir o SIGA, aguardar login manual e manter a sessao pronta para comandos guiados em tempo real.
- Adicionado registro das acoes assistidas em `brain/live_assist_actions.jsonl` para servir de base ao fluxo definitivo de automacao.

## 0.2.2 - 2026-05-25

- Corrigida a localizacao de contribuinte por `CGF` com suporte a formatos mascarados (ex.: `06.240.894-1`).
- Melhorada a confirmacao de entrada na tela do cliente apos clique visual, evitando falso negativo de "contribuinte nao encontrado".

## 0.2.1 - 2026-05-25

- Removido o fluxo de pesquisa e extracao avulsa por `CNPJ` no GUI.
- Removido tambem o argumento `--extract-cnpj` do CLI para manter o produto somente no fluxo em lote.
- GUI mantida somente com fluxo em lote por planilha `.xlsx` (coluna `cgf`) e mes de referencia.

## 0.2.0 - 2026-05-25

- Adicionada selecao de planilha `.xlsx` na GUI para processamento em lote via coluna `cgf`.
- Adicionada selecao de mes de referencia na GUI.
- Implementado fluxo em lote para pesquisar contribuinte por `CGF`, abrir `Informacoes Fiscais` e baixar arquivos fiscais de `Emissor` e `Destinatario`.
- Padronizada a saida por contribuinte e mes dentro da pasta `saida/`.
