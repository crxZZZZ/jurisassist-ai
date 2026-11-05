"""Restores ONLY into jurisassist_restore_test. Never overwrites the application database."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from backup import ROOT, docker


def run(args, **kwargs):
    return subprocess.run(  # noqa: S603 - internal fixed commands, no shell.
        [docker(), "compose", "exec", "-T", "db", *args], cwd=ROOT, check=True, **kwargs
    )  # noqa: S603


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument(
        "--target",
        default="jurisassist_restore_test",
        choices=["jurisassist_restore_test", "jurisassist_restore_test_final"],
    )
    args = parser.parse_args()
    target = args.backup.resolve(strict=True)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    expected = target.with_suffix(".sha256").read_text(encoding="ascii").strip()
    if actual != expected:
        raise SystemExit("Checksum inválido; restauração interrompida.")
    database = args.target
    # CREATE fails safely if a previous restore test exists; no automatic DROP or overwrite.
    run(["createdb", "-U", "jurisassist", database])
    with target.open("rb") as stream:
        run(
            ["pg_restore", "-U", "jurisassist", "--no-owner", "--exit-on-error", "-d", database],
            stdin=stream,
        )
    counts = run(
        [
            "psql",
            "-U",
            "jurisassist",
            "-d",
            database,
            "-Atc",
            "SELECT 'users='||count(*) FROM users UNION ALL SELECT 'documents='||count(*) FROM documents UNION ALL SELECT 'chunks='||count(*) FROM chunks;",
        ],
        capture_output=True,
        text=True,
    )
    print(
        json.dumps(
            {"status": "restored", "database": database, "counts": counts.stdout.splitlines()}
        )
    )
    print("O banco de verificação foi preservado para inspeção. Não afeta o banco principal.")


if __name__ == "__main__":
    main()
