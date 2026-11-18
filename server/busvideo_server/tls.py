"""TLS for the garage server: a private certificate authority (CA) and a server certificate.

The garage has no public domain, so a public CA cannot issue a certificate. The server creates its own CA
once (ca.crt / ca.key) and issues the server certificate from it (server.crt / server.key). Every bus pins
that CA (CA_CERT in client.env): the bus only talks to a server presenting a certificate signed by it, which
blocks anyone on the Wi-Fi from impersonating the garage. Operators install ca.crt in their PC/phone once
so the browser shows the padlock. Re-running keeps the CA and only renews the server certificate, so
already-installed buses keep trusting the server after an IP change.

Uses the `cryptography` package (server dependency). The bus client needs only the standard library.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3650          # 10 years
SERVER_DAYS = 730       # 2 years: Apple/Chrome only trust server certificates valid for <= 825 days
RENEW_BEFORE_DAYS = 45  # renew_if_needed() issues a new server cert this many days before expiry
CA_CRT, CA_KEY, SERVER_CRT, SERVER_KEY = "ca.crt", "ca.key", "server.crt", "server.key"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _write_private(path: Path, key) -> None:
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _load_ca(out_dir: Path):
    key = serialization.load_pem_private_key((out_dir / CA_KEY).read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate((out_dir / CA_CRT).read_bytes())
    return key, cert


def local_ips() -> list[str]:
    """Best-effort list of this machine's IPv4 addresses (no external packet is sent)."""
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))   # TEST-NET address: only used to pick the outbound interface
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def generate(out_dir: Path, ips: list[str] | None = None, dns_names: list[str] | None = None,
             org: str = "Bus Video", ca_days: int = CA_DAYS, server_days: int = SERVER_DAYS) -> dict:
    """Create (or reuse) the CA and issue a fresh server certificate. Returns the file paths and SANs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ips = list(dict.fromkeys((ips or []) + ["127.0.0.1"]))
    dns_names = list(dict.fromkeys((dns_names or []) + ["localhost"]))
    now = _now()

    reused_ca = (out_dir / CA_KEY).exists() and (out_dir / CA_CRT).exists()
    if reused_ca:
        ca_key, ca_cert = _load_ca(out_dir)
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                             x509.NameAttribute(NameOID.COMMON_NAME, f"{org} Garagem CA")])
        ca_cert = (x509.CertificateBuilder()
                   .subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(minutes=5))
                   .not_valid_after(now + dt.timedelta(days=ca_days))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                                content_commitment=False, key_encipherment=False,
                                                data_encipherment=False, key_agreement=False,
                                                encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
                   .sign(ca_key, hashes.SHA256()))
        _write_private(out_dir / CA_KEY, ca_key)
        _write_cert(out_dir / CA_CRT, ca_cert)

    srv_key = ec.generate_private_key(ec.SECP256R1())
    san = [x509.DNSName(d) for d in dns_names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    srv_cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                                         x509.NameAttribute(NameOID.COMMON_NAME, f"{org} Servidor da Garagem")]))
                .issuer_name(ca_cert.subject).public_key(srv_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(minutes=5))
                .not_valid_after(now + dt.timedelta(days=server_days))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=False,
                                             crl_sign=False, content_commitment=False, data_encipherment=False,
                                             key_agreement=False, encipher_only=False, decipher_only=False),
                               critical=True)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
    _write_private(out_dir / SERVER_KEY, srv_key)
    _write_cert(out_dir / SERVER_CRT, srv_cert)
    return {
        "ca_crt": str(out_dir / CA_CRT), "ca_key": str(out_dir / CA_KEY),
        "server_crt": str(out_dir / SERVER_CRT), "server_key": str(out_dir / SERVER_KEY),
        "ips": ips, "dns": dns_names, "reused_ca": reused_ca,
        "server_expires": srv_cert.not_valid_after_utc.date().isoformat(),
        "ca_expires": ca_cert.not_valid_after_utc.date().isoformat(),
    }


def days_left(cert_path: Path) -> int:
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    return (cert.not_valid_after_utc - _now()).days


def renew_if_needed(cert_path: str, key_path: str, before_days: int = RENEW_BEFORE_DAYS) -> bool:
    """Re-issue the server certificate (same CA, same SANs) when it is about to expire. Returns True if renewed."""
    cert_path, key_path = Path(cert_path), Path(key_path)
    if not cert_path.exists() or not key_path.exists():
        return False
    out_dir = cert_path.parent
    if not ((out_dir / CA_KEY).exists() and (out_dir / CA_CRT).exists()):
        return False
    if days_left(cert_path) > before_days:
        return False
    current = info(cert_path)["san"]
    ips = [n for n in current if n.replace(".", "").isdigit() or ":" in n]
    dns = [n for n in current if n not in ips]
    generate(out_dir, ips, dns)
    return True


def info(cert_path: Path) -> dict:
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(v) for v in san.get_values_for_type(x509.IPAddress)] + san.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []
    return {"subject": cert.subject.rfc4514_string(), "issuer": cert.issuer.rfc4514_string(),
            "not_after": cert.not_valid_after_utc.isoformat(), "san": names}
