# SIGA Automação

Automação corporativa para extração em lote de documentos fiscais no SIGA da Sefaz-CE.

O **SIGA Automação** foi criado para reduzir tempo operacional, padronizar rotinas repetitivas e aumentar a confiabilidade da extração de documentos fiscais. Com ele, sua equipe consegue solicitar, localizar e baixar informações fiscais com muito menos cliques, menos retrabalho e mais rastreabilidade.

## Diferenciais

- Elimina navegação manual repetitiva no portal SIGA.
- Processa em lote NF-e, NFC-e e CT-e.
- Funciona com planilha `.xlsx` ou entrada manual na GUI.
- Organiza automaticamente os arquivos por `COD - EMPRESA - CNPJ`.
- Mantém logs, avisos e saídas estruturadas para facilitar auditoria.

## Público indicado

- Escritórios de contabilidade.
- Departamentos fiscais e financeiros.
- Equipes de backoffice com alto volume de empresas.
- Operações que precisam de rotina padronizada e repetível.

## O que a solução entrega

- Interface gráfica com foco em operação assistida.
- Execução por terminal para rotinas automatizadas e integrações.
- Navegação controlada com sessão autenticada reaproveitável.
- Solicitação em lote dos detalhamentos antes da Central de Downloads.
- Salvamento dos arquivos com extensão real preservada.
- Geração de `.txt` quando um CNPJ ou download não é localizado.

## Como usar

### 1. Preparar a planilha

Crie ou utilize uma planilha `.xlsx` com as colunas:

- `COD`
- `EMPRESA`
- `CNPJ`

Os CNPJs devem ser mantidos com 14 dígitos, incluindo zeros à esquerda.

### 2. Abrir a GUI

Você pode executar a interface gráfica com:

```powershell
.\.venv\Scripts\python.exe .\main_gui.py
```

Ou, se já tiver instalado:

```powershell
.\dist\siga-automacao-gui.exe
```

Na GUI, o fluxo recomendado é:

1. Carregar a planilha ou usar a entrada manual.
2. Selecionar mês, ano, documentos e pasta de saída.
3. Iniciar o navegador.
4. Fazer o login manual no SIGA.
5. Executar a extração.

### 3. Usar via terminal

```powershell
.\.venv\Scripts\python.exe .\src\main.py
```

O terminal mantém o mesmo motor de extração da GUI, mas é ideal para rotinas automatizadas, integrações e uso mais técnico.

## Resultado esperado

Com o SIGA Automação, a operação deixa de depender de navegação manual repetitiva e passa a seguir um fluxo padronizado, rastreável e pronto para uso em contexto corporativo.

## Estrutura de saída

Os arquivos são organizados automaticamente em uma estrutura previsível:

```text
<pasta de saída>/<COD - EMPRESA - CNPJ>/<mês>/<tipo de documento>/
```

Essa organização facilita conferência, arquivamento e compartilhamento interno.

## Compilação e distribuição

### Executável da GUI

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean siga-automacao-gui.spec
```

### Instalador Windows

Abra `installer\siga-automacao.iss` no Inno Setup e clique em `Compile`.

O instalador final será gerado em `dist\installer\`.

## Recursos de operação

- Reutilização de sessão autenticada, quando disponível.
- Compatibilidade com certificado digital e políticas locais do navegador.
- Menu de ajuda na GUI com passo a passo de uso.
- Ícones e logo próprios no executável e no instalador.

## Licenciamento

Copyright © 2026 Barreira & Associados. Todos os direitos reservados.

Este software é de propriedade privada e confidencial. O uso deste projeto é restrito exclusivamente às pessoas, empresas ou equipes autorizadas pelo proprietário. Consulte o arquivo `LICENSE` na raiz do projeto para mais detalhes.
