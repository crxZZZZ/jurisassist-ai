"""Bounded read-only load test with an ephemeral account; no inference load."""

import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from jurisassist.db import session_factory
from jurisassist.models import Audit, Session, User
from jurisassist.security import hasher
from sqlalchemy import delete


def main():
    identifier = str(uuid4())
    email, password = f"load-{identifier}@local.invalid", secrets.token_urlsafe(24)
    with session_factory()() as db:
        db.add(
            User(
                id=identifier,
                email=email,
                name="Carga temporária",
                password_hash=hasher.hash(password),
            )
        )
        db.commit()
    env = os.environ.copy()
    env.update({"LOAD_EMAIL": email, "LOAD_PASSWORD": password, "LOAD_MODE": "read"})
    Path("reports").mkdir(exist_ok=True)
    try:
        result = subprocess.run(  # noqa: S603 - fixed local test invocation; credentials only in environment.
            [
                sys.executable,
                "-m",
                "locust",
                "-f",
                "tests/load/locustfile.py",
                "--host",
                "http://127.0.0.1:8080",
                "--headless",
                "--users",
                "5",
                "--spawn-rate",
                "5",
                "--run-time",
                "20s",
                "--tags",
                "read",
                "--csv",
                "reports/api-load",
                "--only-summary",
            ],
            env=env,
            check=False,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        with session_factory()() as db:
            db.execute(delete(Audit).where(Audit.actor_id == identifier))
            db.execute(delete(Session).where(Session.user_id == identifier))
            db.execute(delete(User).where(User.id == identifier))
            db.commit()


if __name__ == "__main__":
    main()
