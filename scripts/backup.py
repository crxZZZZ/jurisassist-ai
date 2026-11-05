"""Streaming pg_dump via Docker; works on Windows without PowerShell binary redirection."""

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def docker():
    binary = shutil.which("docker")
    if not binary:
        candidate = Path.home() / "AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
        if candidate.exists():
            binary = str(candidate)
    if not binary:
        raise SystemExit("Docker não encontrado.")
    return binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data/backups")
    parser.add_argument(
        "--database", default="jurisassist", choices=["jurisassist", "jurisassist_restore_test"]
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = args.output / f"{args.database}-{name}.dump"
    with target.open("wb") as stream:
        result = subprocess.run(  # noqa: S603 - executable is resolved locally; arguments are fixed/allowlisted.
            [
                docker(),
                "compose",
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                "jurisassist",
                "-Fc",
                args.database,
            ],
            cwd=ROOT,
            stdout=stream,
            check=False,
        )  # noqa: S603
    if result.returncode:
        target.unlink(missing_ok=True)
        raise SystemExit("Backup falhou; arquivo incompleto removido.")
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".sha256").write_text(checksum, encoding="ascii")
    print(json.dumps({"backup": str(target), "sha256": checksum, "bytes": target.stat().st_size}))


if __name__ == "__main__":
    main()
