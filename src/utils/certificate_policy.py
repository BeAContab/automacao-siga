from __future__ import annotations

"""Política local para seleção automática do certificado de cliente no navegador."""

import json
import logging
import subprocess
import winreg
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT, Settings


LOGGER = logging.getLogger(__name__)

CLIENT_AUTH_EKU = "1.3.6.1.5.5.7.3.2"
CERTIFICATE_URL_PATTERNS = (
    "https://sso.sefaz.ce.gov.br",
    "https://siga.sefaz.ce.gov.br",
)
POLICY_PATHS = {
    "chrome": r"Software\Policies\Google\Chrome\AutoSelectCertificateForUrls",
    "msedge": r"Software\Policies\Microsoft\Edge\AutoSelectCertificateForUrls",
}


class CertificatePolicyError(RuntimeError):
    pass


@dataclass(slots=True)
class ClientCertificate:
    """Representa um certificado de autenticação de cliente disponível no repositório do usuário."""
    subject_cn: str
    not_after: str
    thumbprint: str


@dataclass(slots=True)
class CertificatePolicyResult:
    """Resultado consolidado da tentativa de aplicar ou limpar a política."""
    subject_cn: str | None
    applied: bool
    registry_path: str | None = None
    reg_file_path: Path | None = None
    # Sinaliza que havia mais de um certificado elegível e nenhuma escolha foi feita,
    # então a política não foi aplicada por segurança (evita usar o CNPJ errado).
    requires_manual_selection: bool = False


# Um seletor recebe a lista de certificados elegíveis e devolve o escolhido, ou None para cancelar.
CertificateSelector = Callable[[Sequence[ClientCertificate]], ClientCertificate | None]


def configure_auto_certificate_selection(
    settings: Settings,
    selector: CertificateSelector | None = None,
) -> CertificatePolicyResult:
    """Cria ou atualiza a política de seleção automática do certificado de cliente.

    Quando há mais de um certificado elegível, a escolha não é automática: o `selector`
    (quando fornecido) decide qual usar. Sem seletor e com ambiguidade, a política não é
    aplicada, evitando selecionar silenciosamente o certificado de outra empresa.
    """
    policy_path = POLICY_PATHS.get(settings.browser_channel)
    if not policy_path:
        LOGGER.info("Ignorando a politica de certificado para canal de navegador nao suportado: %s", settings.browser_channel)
        return CertificatePolicyResult(subject_cn=None, applied=False)

    certificates = _list_client_auth_certificates()
    if not certificates:
        LOGGER.warning("Nenhum certificado de autenticacao de cliente com chave privada foi encontrado em CurrentUser\\My")
        return CertificatePolicyResult(subject_cn=None, applied=False, registry_path=policy_path)

    if len(certificates) == 1:
        subject_cn = certificates[0].subject_cn
    else:
        # Mais de um certificado elegível: não escolher automaticamente por validade.
        if selector is None:
            LOGGER.warning(
                "Foram encontrados %s certificados de autenticacao elegiveis; a politica nao foi "
                "aplicada automaticamente para evitar usar o certificado incorreto.",
                len(certificates),
            )
            return CertificatePolicyResult(
                subject_cn=None,
                applied=False,
                registry_path=policy_path,
                requires_manual_selection=True,
            )
        chosen = selector(certificates)
        if chosen is None:
            LOGGER.info("Selecao de certificado cancelada pelo operador; politica nao aplicada.")
            return CertificatePolicyResult(
                subject_cn=None,
                applied=False,
                registry_path=policy_path,
                requires_manual_selection=True,
            )
        subject_cn = chosen.subject_cn

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, policy_path, 0, winreg.KEY_SET_VALUE) as key:
            for index, payload in enumerate(_policy_payloads(subject_cn), start=1):
                winreg.SetValueEx(key, str(index), 0, winreg.REG_SZ, json.dumps(payload, ensure_ascii=True))
    except PermissionError:
        reg_file_path = _write_reg_file(policy_path, subject_cn)
        LOGGER.warning(
            "Nao foi possivel gravar a politica de certificado em HKCU por erro de permissao. Arquivo gerado: %s",
            reg_file_path,
        )
        return CertificatePolicyResult(
            subject_cn=subject_cn,
            applied=False,
            registry_path=policy_path,
            reg_file_path=reg_file_path,
        )

    LOGGER.info(
        "Politica de selecao automatica de certificado configurada para %s usando o CN '%s'",
        settings.browser_channel,
        subject_cn,
    )
    return CertificatePolicyResult(subject_cn=subject_cn, applied=True, registry_path=policy_path)


def clear_auto_certificate_selection(settings: Settings) -> bool:
    """Remove as entradas criadas pela política quando o usuário pede limpeza."""
    policy_path = POLICY_PATHS.get(settings.browser_channel)
    if not policy_path:
        return False

    removed = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, policy_path, 0, winreg.KEY_SET_VALUE) as key:
            for index in range(1, len(CERTIFICATE_URL_PATTERNS) + 1):
                try:
                    winreg.DeleteValue(key, str(index))
                    removed = True
                except FileNotFoundError:
                    continue
    except FileNotFoundError:
        return False
    except PermissionError as exc:
        raise CertificatePolicyError(
            f"Sem permissao para remover a politica de certificado em HKCU\\{policy_path}"
        ) from exc

    LOGGER.info("Politica de selecao automatica de certificado removida para %s", settings.browser_channel)
    return removed


def _list_client_auth_certificates() -> list[ClientCertificate]:
    """Lista os certificados do usuário que suportam autenticação de cliente, do mais recente ao mais antigo."""
    command = (
        "$certs = Get-ChildItem Cert:\\CurrentUser\\My | "
        "Where-Object { $_.HasPrivateKey -and "
        f"($_.EnhancedKeyUsageList | Where-Object {{ $_.ObjectId -eq '{CLIENT_AUTH_EKU}' }}) }} | "
        "Sort-Object NotAfter -Descending; "
        "$list = $certs | ForEach-Object { [PSCustomObject]@{ "
        "cn = $_.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false); "
        "notAfter = $_.NotAfter.ToString('dd/MM/yyyy'); "
        "thumbprint = $_.Thumbprint } }; "
        "ConvertTo-Json -InputObject @($list) -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CertificatePolicyError(result.stderr.strip() or "Falha ao ler o armazenamento de certificados CurrentUser")

    raw_output = result.stdout.strip()
    if not raw_output:
        return []

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise CertificatePolicyError("Nao foi possivel interpretar a lista de certificados retornada pelo PowerShell") from exc

    # ConvertTo-Json devolve um objeto (dict) quando ha apenas um item e uma lista quando ha varios.
    entries = parsed if isinstance(parsed, list) else [parsed]

    certificates: list[ClientCertificate] = []
    for entry in entries:
        subject_cn = str(entry.get("cn") or "").strip()
        if not subject_cn:
            # Sem CN nao ha como montar o filtro da politica; ignora o item.
            continue
        certificates.append(
            ClientCertificate(
                subject_cn=subject_cn,
                not_after=str(entry.get("notAfter") or "").strip(),
                thumbprint=str(entry.get("thumbprint") or "").strip(),
            )
        )
    return certificates


def _policy_payloads(subject_cn: str) -> list[dict[str, object]]:
    """Monta os blocos JSON que o Chrome/Edge espera na política de certificado."""
    return [
        {
            "pattern": pattern,
            "filter": {
                "SUBJECT": {
                    "CN": subject_cn,
                },
            },
        }
        for pattern in CERTIFICATE_URL_PATTERNS
    ]


def _write_reg_file(policy_path: str, subject_cn: str) -> Path:
    """Gera um arquivo .reg quando o Windows impede escrita direta no registro."""
    output_path = PROJECT_ROOT / "logs" / "chrome-certificate-policy.reg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path = rf"HKEY_CURRENT_USER\{policy_path}"
    lines = [
        "Windows Registry Editor Version 5.00",
        "",
        f"[{registry_path}]",
    ]
    for index, payload in enumerate(_policy_payloads(subject_cn), start=1):
        value = json.dumps(payload, ensure_ascii=True).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'"{index}"="{value}"')
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-16")
    return output_path
