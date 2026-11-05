import json
import re
import time
from pathlib import Path
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from jurisassist import telemetry
from jurisassist.config import get_settings
from jurisassist.models import Chunk, Document
from jurisassist.retrieval import basis_state, citation, get_article, search
from jurisassist.schemas import (
    ArticleArguments,
    ContractAnswer,
    DocumentsArguments,
    LegalAnswer,
    QueryIntent,
    ToolArguments,
)


class ModelUnavailable(RuntimeError):
    pass


class InvalidEvidence(ValueError):
    pass


def prompt(version: str | None = None):
    version = version or get_settings().prompt_version
    if version not in {"v1", "v2"}:
        raise ValueError("Versão de prompt inválida.")
    return (Path(__file__).parent / "prompts" / f"{version}.md").read_text(encoding="utf-8")


class Ollama:
    def request(self, messages, schema=None, tools=None):
        settings = get_settings()
        payload = {
            "model": settings.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "5m",
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 2200},
        }
        if schema:
            payload["format"] = schema if isinstance(schema, dict) else schema.model_json_schema()
        if tools:
            payload["tools"] = tools
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=settings.llm_timeout, trust_env=False) as client:
                response = client.post(f"{settings.ollama_url.rstrip('/')}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            telemetry.tokens.labels("input").inc(data.get("prompt_eval_count", 0))
            telemetry.tokens.labels("output").inc(data.get("eval_count", 0))
            return data["message"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ModelUnavailable(
                "O modelo local não está disponível. Confira o Ollama e o modelo instalado."
            ) from exc
        finally:
            telemetry.llm.observe(time.perf_counter() - started)

    def structured(self, messages, schema: type[BaseModel], reference_ids=None):
        wire_schema = schema.model_json_schema()
        if reference_ids:
            if schema is ContractAnswer:
                contract_ids = reference_ids["contract"]
                law_ids = reference_ids["law"]
                wire_schema["$defs"]["Claim"]["properties"]["citation_ids"]["items"]["enum"] = (
                    contract_ids
                )
                finding = wire_schema["$defs"]["ContractFinding"]["properties"]
                finding["contract_chunk_id"]["enum"] = contract_ids
                finding["citation_ids"]["items"]["enum"] = law_ids
                # The backend resolves the literal quotation from the selected chunk.
                # Asking a small LLM to retype legal text introduces avoidable errors.
                finding["quote"] = {"type": "string", "const": ""}
            elif schema is LegalAnswer:
                wire_schema["$defs"]["Claim"]["properties"]["citation_ids"]["items"]["enum"] = (
                    reference_ids["law"]
                )
        result = self.request(messages, schema=wire_schema)
        return schema.model_validate_json(result.get("content", ""))


def tool_definition(name, description, schema):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema.model_json_schema(),
        },
    }


TOOLS = [
    tool_definition(
        "search_legislation", "Pesquisar legislação federal trabalhista e contratos.", ToolArguments
    ),
    tool_definition(
        "get_article",
        "Consultar artigo de uma fonte pelo source_id e número do artigo.",
        ArticleArguments,
    ),
    tool_definition(
        "search_document",
        "Consultar exclusivamente documento pertencente ao usuário.",
        DocumentsArguments,
    ),
]


def validate_legal(answer: LegalAnswer, evidence: list[dict]):
    ids = {item["id"] for item in evidence}
    if answer.status == "answered" and not answer.claims:
        raise InvalidEvidence("Resposta jurídica sem afirmações fundamentadas.")
    if answer.status != "answered" and answer.claims:
        raise InvalidEvidence("Resposta sem suporte não pode conter conclusões.")
    for claim in answer.claims:
        if not set(claim.citation_ids) <= ids:
            raise InvalidEvidence("Referência inexistente ou fora da recuperação autorizada.")
    if answer.status == "clarification" and not answer.questions:
        raise InvalidEvidence("Esclarecimento sem pergunta.")


def validate_contract(answer: ContractAnswer, legal: list[dict], contract: list[dict]):
    laws = {x["id"] for x in legal}
    clauses = {x["id"]: x for x in contract}
    for claim in answer.obligations + answer.deadlines:
        if not set(claim.citation_ids) <= clauses.keys():
            raise InvalidEvidence("Obrigação ou prazo sem cláusula correspondente.")
    for finding in answer.findings:
        if finding.contract_chunk_id not in clauses or not set(finding.citation_ids) <= laws:
            raise InvalidEvidence("Ponto de atenção com referência inválida.")
        if not finding.quote.strip() or " ".join(finding.quote.split()) not in " ".join(
            clauses[finding.contract_chunk_id]["text"].split()
        ):
            raise InvalidEvidence("Trecho citado não corresponde ao contrato.")


def safe_insufficient(
    reason="Não encontrei evidências suficientes na base aprovada para responder com segurança.",
):
    return LegalAnswer(status="insufficient", summary=reason).model_dump()


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict]
    evidence: list[dict]
    messages: list[dict]
    result: dict
    attempt: int
    invalid: bool
    error: str


def research_chat(
    db, owner_id, question, history=None, gateway=None, mode="hybrid", progress=None, version=None
):
    gateway = gateway or Ollama()
    progress = progress or (lambda _: None)
    basis = basis_state(db)

    def route(state):
        progress("Delimitando a consulta")
        # Requests requiring data outside v1 are never answered from model memory.
        historical = re.search(
            r"(?:em|antes de|no ano de|vigente em|valiam em|regra de)\s+(?:19\d{2}|20\d{2})\b",
            question,
            re.I,
        )
        outside = re.search(
            r"jurisprud[eê]ncia|conven[çc][aã]o coletiva|n[úu]mero do processo|calcule.*rescis|cota[çc][aã]o.*a[çc][oõ]es|rem[eé]dio.*tomar",
            question,
            re.I,
        )
        if historical or outside:
            return {
                "result": safe_insufficient(
                    "Esta consulta depende de vigência histórica, jurisprudência, norma coletiva ou cálculo que não está coberto pela base desta versão."
                )
            }
        if basis["indexed_sources"] == 0:
            return {
                "result": safe_insufficient(
                    "A base jurídica ainda não foi aprovada e indexada. Peça ao administrador para preparar as fontes."
                )
            }
        intent_messages = [
            {
                "role": "system",
                "content": (Path(__file__).parent / "prompts/intent-v1.md").read_text(
                    encoding="utf-8"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "history": [
                            {"role": m["role"], "content": m["content"][:600]}
                            for m in (history or [])[-4:]
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            intent = gateway.structured(intent_messages, QueryIntent)
        except ValidationError:
            return {
                "result": safe_insufficient(
                    "Não consegui delimitar uma consulta jurídica válida. Reformule sua pergunta."
                )
            }
        if intent.action == "out_of_scope":
            return {
                "result": safe_insufficient(
                    "Posso ajudar com pesquisa trabalhista, terceirização e contratos, usando referências verificáveis. Formule uma pergunta sobre esses temas."
                )
            }
        if intent.action == "clarification":
            return {
                "result": LegalAnswer(
                    status="clarification",
                    summary="Preciso de um pouco mais de contexto para pesquisar.",
                    questions=intent.questions
                    or ["Qual é a questão trabalhista ou contratual que você deseja esclarecer?"],
                ).model_dump()
            }
        return {}

    def research(state):
        progress("Consultando fontes e ferramentas")
        evidence = search(db, owner_id, question, mode=mode)
        messages = [
            {
                "role": "system",
                "content": "Planeje a pesquisa. Use apenas ferramentas disponibilizadas, no máximo três chamadas. Fontes: clt, terceirizacao, codigo-civil. Não responda à pergunta ainda.",
            },
            {"role": "user", "content": question},
        ]
        plan = gateway.request(messages, tools=TOOLS)
        # Explicit bounded tool calling; no arbitrary URLs, SQL or file access.
        for call in plan.get("tool_calls", [])[:3]:
            function = call.get("function", {})
            name, raw = function.get("name"), function.get("arguments", {})
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    continue
            try:
                if name == "search_legislation":
                    args = ToolArguments.model_validate(raw)
                    found = search(db, owner_id, args.query, mode=mode, limit=3)
                elif name == "get_article":
                    args = ArticleArguments.model_validate(raw)
                    found = get_article(db, args.source_id, args.article)
                elif name == "search_document":
                    args = DocumentsArguments.model_validate(raw)
                    found = search(
                        db, owner_id, args.query, mode=mode, limit=3, document_id=args.document_id
                    )
                else:
                    continue
                telemetry.tools.labels(name).inc()
                evidence.extend(found)
            except ValidationError:
                continue
        evidence = list({x["id"]: x for x in evidence}.values())[:10]
        # History is not an evidence source and its size is bounded.
        messages = [{"role": "system", "content": prompt(version)}]
        for item in (history or [])[-6:]:
            messages.append({"role": item["role"], "content": item["content"][:1200]})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "untrusted_evidence": evidence, "basis": basis},
                    ensure_ascii=False,
                ),
            }
        )
        return {"evidence": evidence, "messages": messages, "attempt": 0}

    def draft(state):
        progress("Elaborando resposta fundamentada")
        try:
            answer = gateway.structured(
                state["messages"],
                LegalAnswer,
                reference_ids={"law": [item["id"] for item in state["evidence"]]},
            )
            return {
                "result": answer.model_dump(),
                "attempt": state["attempt"] + 1,
                "invalid": False,
            }
        except ValidationError:
            return {"result": {}, "attempt": state["attempt"] + 1, "invalid": True}

    def validate(state):
        progress("Validando referências")
        try:
            answer = LegalAnswer.model_validate(state["result"])
            validate_legal(answer, state["evidence"])
            return {"invalid": False}
        except (ValidationError, InvalidEvidence):
            if state["attempt"] >= 2:
                return {
                    "invalid": False,
                    "result": safe_insufficient(
                        "A resposta gerada não passou na validação das referências. Reformule a pergunta ou solicite revisão humana."
                    ),
                }
            return {
                "invalid": True,
                "messages": state["messages"]
                + [
                    {
                        "role": "user",
                        "content": "A saída anterior foi rejeitada. Gere novamente no schema, usando exclusivamente os IDs das evidências. Se faltar suporte, retorne insufficient sem claims.",
                    }
                ],
            }

    graph = StateGraph(AgentState)
    graph.add_node("route", route)
    graph.add_node("research", research)
    graph.add_node("draft", draft)
    graph.add_node("validate", validate)
    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        lambda s: "done" if s.get("result") else "research",
        {"done": END, "research": "research"},
    )
    graph.add_edge("research", "draft")
    graph.add_edge("draft", "validate")
    graph.add_conditional_edges(
        "validate", lambda s: "retry" if s["invalid"] else "done", {"retry": "draft", "done": END}
    )
    state = graph.compile().invoke({"question": question}, config={"recursion_limit": 12})
    result = state["result"]
    used_ids = {ref for claim in result.get("claims", []) for ref in claim["citation_ids"]}
    result.update(
        {
            "citations": [e for e in state.get("evidence", []) if e["id"] in used_ids],
            "basis": basis,
            "model": get_settings().model,
            "prompt_version": version or get_settings().prompt_version,
        }
    )
    return result


def analyze_contract(
    db, owner_id, document_id, gateway=None, progress=None, mode="hybrid", version=None
):
    from sqlalchemy import select

    gateway = gateway or Ollama()
    progress = progress or (lambda _: None)
    doc = db.get(Document, document_id)
    if doc is None or doc.owner_id != owner_id or doc.status != "ready":
        raise ValueError("Contrato indisponível ou ainda não indexado.")
    if basis_state(db)["indexed_sources"] == 0:
        raise ValueError("A base jurídica precisa ser aprovada e indexada antes da análise.")
    chunks = list(
        db.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal))
    )
    findings, obligations, deadlines, summaries, evidence = [], [], [], [], {}
    started = time.monotonic()
    for offset in range(0, len(chunks), 6):
        if time.monotonic() - started > 1800:
            raise ModelUnavailable("A análise excedeu 30 minutos. Use um contrato menor.")
        progress(f"Analisando trechos {offset + 1}–{min(offset + 6, len(chunks))} de {len(chunks)}")
        clauses = [citation(db, c) for c in chunks[offset : offset + 6]]
        query = (
            "obrigações contrato prestação serviços terceirização responsabilidade prazo "
            + " ".join(c["text"][:180] for c in clauses)
        )
        legal = search(db, owner_id, query, mode=mode, limit=5)
        messages = [
            {"role": "system", "content": prompt(version)},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Analise este lote do contrato. Obrigações e prazos citam IDs do contrato. Pontos de atenção citam lei e cláusula. Não declare invalidade sem suporte.",
                        "untrusted_contract": clauses,
                        "untrusted_law": legal,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        for attempt in range(2):
            try:
                answer = gateway.structured(
                    messages,
                    ContractAnswer,
                    reference_ids={
                        "contract": [item["id"] for item in clauses],
                        "law": [item["id"] for item in legal],
                    },
                )
                clause_texts = {item["id"]: item["text"] for item in clauses}
                for finding in answer.findings:
                    if finding.contract_chunk_id in clause_texts:
                        finding.quote = clause_texts[finding.contract_chunk_id]
                validate_contract(answer, legal, clauses)
                break
            except (ValidationError, InvalidEvidence) as exc:
                if attempt:
                    raise InvalidEvidence(
                        "A análise não passou na validação de evidências; nenhum resultado parcial foi publicado."
                    ) from exc
                messages.append(
                    {
                        "role": "user",
                        "content": "Corrija as referências e use quotes literais dos trechos apresentados. Não crie IDs.",
                    }
                )
        summaries.append(answer.summary)
        findings.extend(x.model_dump() for x in answer.findings)
        obligations.extend(x.model_dump() for x in answer.obligations)
        deadlines.extend(x.model_dump() for x in answer.deadlines)
        evidence.update({x["id"]: x for x in clauses + legal})
    return {
        "summary": "\n\n".join(summaries),
        "findings": findings,
        "obligations": obligations,
        "deadlines": deadlines,
        "citations": list(evidence.values()),
        "coverage": {"processed_chunks": len(chunks), "total_chunks": len(chunks)},
        "basis": basis_state(db),
        "model": get_settings().model,
        "prompt_version": version or get_settings().prompt_version,
    }
