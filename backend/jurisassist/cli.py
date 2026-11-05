import argparse
import getpass
import json
import os
import shutil
import sys

from sqlalchemy import select

from jurisassist.config import get_settings
from jurisassist.db import session_factory
from jurisassist.ingestion import bootstrap_sources, fetch_source
from jurisassist.models import User
from jurisassist.security import hasher


def preflight():
    free = shutil.disk_usage(".").free / 2**30
    checks = {
        "python": sys.version.split()[0],
        "free_disk_gib": round(free, 1),
        "disk_ok": free >= 15,
        "docker": bool(shutil.which("docker")),
        "ollama": bool(shutil.which("ollama")),
        "node": bool(shutil.which("node")),
    }
    print(json.dumps(checks, indent=2))
    if not checks["disk_ok"]:
        raise SystemExit("Reserve ao menos 15 GiB antes dos downloads iniciais.")


def main():
    parser = argparse.ArgumentParser(description="JurisAssist · Operação local")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    create = commands.add_parser("create-user")
    create.add_argument("--email")
    create.add_argument("--name")
    create.add_argument("--role", choices=["user", "admin"], default="admin")
    create.add_argument("--password-env", help="Nome de variável com a senha (não o valor).")
    commands.add_parser("init-sources")
    fetch = commands.add_parser("fetch-sources")
    fetch.add_argument("--source", choices=["clt", "terceirizacao", "codigo-civil"])
    commands.add_parser("download-embeddings")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--matrix", action="store_true")
    evaluate.add_argument(
        "--generate", action="store_true", help="Executar o modelo real; pode levar vários minutos."
    )
    evaluate.add_argument("--mode", choices=["text", "vector", "hybrid"], default="hybrid")
    evaluate.add_argument("--prompt", choices=["v1", "v2"], default="v2")
    args = parser.parse_args()
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if args.command == "preflight":
        preflight()
    elif args.command == "create-user":
        email = (args.email or input("E-mail: ")).strip().lower()
        name = (args.name or input("Nome: ")).strip()
        password = (
            os.environ.get(args.password_env, "")
            if args.password_env
            else getpass.getpass("Senha (mínimo 12 caracteres): ")
        )
        if (
            "@" not in email
            or len(email) > 254
            or not name
            or len(name) > 100
            or not 12 <= len(password) <= 256
        ):
            raise SystemExit(
                "E-mail, nome ou senha inválidos. A senha deve ter entre 12 e 256 caracteres."
            )
        with session_factory()() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise SystemExit("Este e-mail já está cadastrado.")
            db.add(
                User(email=email, name=name, role=args.role, password_hash=hasher.hash(password))
            )
            db.commit()
        print("Usuário criado. A senha não foi registrada em logs.")
    elif args.command == "init-sources":
        with session_factory()() as db:
            bootstrap_sources(db, load_snapshots=True)
        print("Fontes cadastradas. Colete e revise antes de indexar.")
    elif args.command == "fetch-sources":
        from jurisassist.ingestion import SOURCES

        with session_factory()() as db:
            bootstrap_sources(db)
            for key in [args.source] if args.source else SOURCES:
                document = fetch_source(db, key)
                print(
                    f"{key}: " + ("nova versão aguardando revisão" if document else "sem mudança")
                )
    elif args.command == "download-embeddings":
        from jurisassist.retrieval import get_embeddings

        preflight()
        result = get_embeddings().query("Validação de pesquisa jurídica em português")
        print(f"Embeddings disponíveis: {len(result)} dimensões.")
    elif args.command == "evaluate":
        from jurisassist.evaluation import evaluate

        modes = ["text", "vector", "hybrid"] if args.matrix else [args.mode]
        prompts = ["v1", "v2"] if args.matrix else [args.prompt]
        for mode in modes:
            for version in prompts:
                report = evaluate(mode=mode, version=version, generate=args.generate)
                print(
                    json.dumps(
                        {k: v for k, v in report.items() if k != "cases"},
                        ensure_ascii=False,
                        indent=2,
                    )
                )


if __name__ == "__main__":
    main()
