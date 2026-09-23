"""Скачать hysteria2-клиент в /usr/local/bin/hysteria (сборка Docker-образа бота)."""

from __future__ import annotations

import os
import pathlib
import shutil
import stat
import sys
import urllib.request

DEST = pathlib.Path("/usr/local/bin/hysteria")
VENDORED = pathlib.Path("/app/bots/hysteria")
VERSION = "2.12.2"


def _chmod_x(path: pathlib.Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> int:
    if VENDORED.is_file():
        shutil.copy(VENDORED, DEST)
        _chmod_x(DEST)
        print("hysteria from bots/hysteria")
        return 0
    arch = os.environ.get("TARGETARCH") or "amd64"
    name = "hysteria-linux-arm64" if arch == "arm64" else "hysteria-linux-amd64"
    urls = [
        f"https://github.com/apernet/hysteria/releases/download/app%2Fv{VERSION}/{name}",
        f"https://download.hysteria.network/app/v{VERSION}/{name}",
    ]
    err: Exception | None = None
    for url in urls:
        try:
            urllib.request.urlretrieve(url, DEST)
            _chmod_x(DEST)
            print("hysteria", url)
            return 0
        except Exception as e:  # noqa: BLE001
            err = e
    print("WARN hysteria download failed:", err, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
