"""API: SSL-контекст для aiohttp.

Причина ошибок CERTIFICATE_VERIFY_FAILED на Windows — антивирусы (Kaspersky,
ESET…) и корпоративные прокси подменяют HTTPS своим корневым сертификатом.
Решение: certifi-бандл + корневые сертификаты из хранилищ Windows (ROOT, CA),
плюс опционально свой бандл (SSL_CA_BUNDLE) или отключение проверки (SSL_VERIFY=false).
"""
from __future__ import annotations

import logging
import ssl
import sys

log = logging.getLogger("sslctx")


def build_ssl_context(ca_bundle: str = "", verify: bool = True) -> ssl.SSLContext:
    if not verify:
        log.warning("Проверка SSL-сертификатов ОТКЛЮЧЕНА (SSL_VERIFY=false) — "
                    "не оставляйте так в проде.")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    if ca_bundle:
        ctx.load_verify_locations(cafile=ca_bundle)
        log.info("SSL: добавлен кастомный CA-бандл %s", ca_bundle)

    if sys.platform == "win32":
        added = 0
        for store_name in ("ROOT", "CA"):
            try:
                for cert, _enc, _name in ssl.enum_certificates(store_name):
                    try:
                        ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
                        added += 1
                    except ssl.SSLError:
                        continue
            except Exception:  # хранилище недоступно — не страшно
                continue
        log.debug("SSL: из хранилищ Windows добавлено сертификатов: %d", added)
    return ctx
