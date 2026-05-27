# SIGA Automacao

Automacao por terminal com Selenium para acessar o SIGA, aguardar login manual e extrair os arquivos fiscais por CGF a partir de uma planilha `.xlsx`.

## Uso

Execute o fluxo interativo:

```powershell
.\.venv\Scripts\python.exe .\main.py
```

Ou informe os parametros diretamente:

```powershell
.\.venv\Scripts\python.exe .\main.py --month Maio --spreadsheet .\cgf.xlsx
```

O terminal vai:

1. pedir o mes de referencia, se nao informado;
2. pedir a planilha `.xlsx`, se nao informada;
3. tentar reaproveitar uma aba do SIGA ja autenticada em um Chrome com CDP ativo;
4. se nao encontrar uma aba valida, abrir o Chrome em um perfil dedicado de automacao para login manual;
5. aguardar `Enter` antes de anexar o Selenium, somente apos o SIGA estar autenticado;
6. conectar o Selenium ao navegador ja autenticado;
7. executar a extracao no mesmo contexto autenticado.

O Selenium se conecta ao Chrome/Edge pela porta de depuracao somente depois do login manual, para manter a mesma sessao sem controlar a etapa do certificado/recaptcha.

## Certificado digital

O navegador e aberto em um perfil dedicado de automacao com CDP ativo. No Windows, a selecao de `Seu certificado digital` usa os certificados instalados no repositario do usuario do Windows.

Esse perfil dedicado evita bloqueios recentes do Chrome ao usar `--remote-debugging-port` com o perfil normal do usuario.

Antes de abrir o navegador, o programa configura a politica local do Chrome/Edge para selecionar automaticamente o certificado de cliente instalado no usuario atual para os dominios do SIGA e SSO.

Para executar sem alterar a politica de certificado:

```powershell
.\.venv\Scripts\python.exe .\main.py --skip-certificate-policy
```

Para remover a politica criada pelo programa:

```powershell
.\.venv\Scripts\python.exe .\main.py --clear-certificate-policy
```

Se o Windows bloquear a gravacao automatica da politica, o programa gera o arquivo `logs/chrome-certificate-policy.reg`. Nesse caso, aplique o arquivo manualmente com uma conta que tenha permissao para alterar politicas do Chrome.

Se quiser tentar usar o perfil normal do Chrome:

```powershell
.\.venv\Scripts\python.exe .\main.py --system-browser-profile
```

Se seus certificados estiverem em outro perfil do Chrome:

```powershell
.\.venv\Scripts\python.exe .\main.py --chrome-profile-directory "Profile 1"
```

Se quiser encerrar os processos existentes do Chrome antes de iniciar a automacao:

```powershell
.\.venv\Scripts\python.exe .\main.py --force-restart-browser
```

## Reaproveitamento de sessao

Se existir um Chrome com CDP ativo e uma aba em `https://siga.sefaz.ce.gov.br/ui/` ja autenticada, a automacao tenta se anexar a essa aba antes de pedir login manual.

Para desabilitar esse comportamento em uma execucao especifica:

```powershell
.\.venv\Scripts\python.exe .\main.py --disable-attach
```

Para desabilitar por configuracao:

```env
PREFER_EXISTING_SIGA_SESSION=false
```

## Live assist

O modo assistido continua disponivel para diagnostico usando a mesma sessao Selenium:

```powershell
.\.venv\Scripts\python.exe .\main.py --live-assist
```

## Logs

- Execucao geral: `logs/run.log`
- Erros: `logs/errors.log`

Arquivos locais sensiveis, certificados, logs, saidas e a pasta `brain/` ficam fora do controle de versao via `.gitignore`.
# automacao-siga
