from __future__ import annotations

import json
import logging
import subprocess
import winreg
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
class CertificatePolicyResult:
    subject_cn: str | None
    applied: bool
    registry_path: str | None = None
    reg_file_path: Path | None = None


def configure_auto_certificate_selection(settings: Settings) -> CertificatePolicyResult:
    policy_path = POLICY_PATHS.get(settings.browser_channel)
    if not policy_path:
        LOGGER.info("Skipping certificate policy for unsupported browser channel: %s", settings.browser_channel)
        return CertificatePolicyResult(subject_cn=None, applied=False)

    subject_cn = _find_client_auth_certificate_cn()
    if not subject_cn:
        LOGGER.warning("No client-auth certificate with private key was found in CurrentUser\\My")
        return CertificatePolicyResult(subject_cn=None, applied=False, registry_path=policy_path)

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, policy_path, 0, winreg.KEY_SET_VALUE) as key:
            for index, payload in enumerate(_policy_payloads(subject_cn), start=1):
                winreg.SetValueEx(key, str(index), 0, winreg.REG_SZ, json.dumps(payload, ensure_ascii=True))
    except PermissionError:
        reg_file_path = _write_reg_file(policy_path, subject_cn)
        LOGGER.warning(
            "Could not write certificate policy to HKCU due to permission error. Generated %s",
            reg_file_path,
        )
        return CertificatePolicyResult(
            subject_cn=subject_cn,
            applied=False,
            registry_path=policy_path,
            reg_file_path=reg_file_path,
        )

    LOGGER.info(
        "Configured certificate auto-selection policy for %s using SUBJECT CN '%s'",
        settings.browser_channel,
        subject_cn,
    )
    return CertificatePolicyResult(subject_cn=subject_cn, applied=True, registry_path=policy_path)


def clear_auto_certificate_selection(settings: Settings) -> bool:
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

    LOGGER.info("Cleared certificate auto-selection policy for %s", settings.browser_channel)
    return removed


def _find_client_auth_certificate_cn() -> str | None:
    command = (
        "$cert = Get-ChildItem Cert:\\CurrentUser\\My | "
        "Where-Object { $_.HasPrivateKey -and "
        f"($_.EnhancedKeyUsageList | Where-Object {{ $_.ObjectId -eq '{CLIENT_AUTH_EKU}' }}) }} | "
        "Sort-Object NotAfter -Descending | Select-Object -First 1; "
        "if ($cert) { "
        "$cert.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) "
        "}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CertificatePolicyError(result.stderr.strip() or "Failed to read CurrentUser certificate store")

    subject_cn = result.stdout.strip()
    return subject_cn or None


def _policy_payloads(subject_cn: str) -> list[dict[str, object]]:
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
