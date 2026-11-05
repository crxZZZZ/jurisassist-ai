# Operação e recuperação

## Saúde e diagnóstico

`/health/live` verifica o processo. `/health/ready` verifica o banco. O status autenticado da aplicação consulta o Ollama e a presença do modelo. Ele distingue modelo ausente, base não preparada e tarefas em andamento; não declara que a inferência foi validada por apenas consultar `/api/tags`.

Métricas autenticadas do processo API ficam em `/api/v1/admin/metrics`: requisições e latências. As métricas do worker são acessíveis pelo proxy autenticado `/api/v1/admin/metrics/worker`, incluindo ferramentas, inferência, tokens, recuperação e tarefas. O servidor interno de métricas do worker não é publicado no host pelo Compose. Logs JSON permitem acompanhar falhas sem conteúdo dos documentos.

```bash
docker compose ps
docker compose logs --tail 100 worker
docker compose logs --tail 50 api
docker compose exec api jurisassist preflight
```

O `preflight` dentro de um container mede o filesystem do container e não descobre programas do host; a checagem principal de espaço deve ser feita pelo script de instalação no host.

Se a IA está pendente, confirme `ollama list`, o servidor em `localhost:11434` e a conectividade do container com `host.docker.internal:11434`. No Linux, ajuste a interface de escuta do Ollama e o firewall para permitir somente a rede Docker.

Se a indexação falhar depois da aprovação, a versão permanece `indexing`. Após corrigir rede, cache ou modelo de embeddings, use **Reenfileirar indexação**. A versão anterior continua disponível até a conclusão. Contratos com falha de indexação podem ser reenviados; a tarefa e seu diagnóstico ficam preservados.

## Backup e restauração verificável

O banco contém textos originais, evidências, vetores, análises, usuários e revisões. É suficiente para recuperar o estado funcional. O cache dos modelos pode ser baixado novamente. Preserve também `.env` em local seguro, fora do repositório. Backups contêm dados de sessão e hashes de senha; trate-os como dados privados.

```powershell
.\.venv\Scripts\python scripts/backup.py
.\.venv\Scripts\python scripts/restore_verify.py data/backups/ARQUIVO.dump
```

O backup usa `pg_dump -Fc` com streaming binário, evitando corrupção por redirecionamento de PowerShell. Gera SHA-256. A restauração confere o hash e cria exclusivamente `jurisassist_restore_test`; falha se esse banco já existir, em vez de sobrescrevê-lo. O script reporta contagens de usuários, documentos e trechos. Compare-as ao banco de origem e faça consultas de leitura antes de considerar a recuperação aprovada.

O banco de verificação permanece para inspeção. Sua remoção é uma ação manual separada. Se o primeiro banco de teste já existir, `--target jurisassist_restore_test_final` permite uma segunda verificação sem sobrescrever o anterior. Para recuperar a aplicação após incidente, restaure em um banco novo e aponte `JURIS_DATABASE_URL` para ele; valide a migração, o login, a busca e as análises antes de substituir o ambiente anterior. Não execute restauração destrutiva sobre o banco principal.

Meta de referência para uso local: backup diário quando a aplicação for usada, perda máxima de dados igual ao intervalo entre backups. O tempo de recuperação deve ser medido com o volume real, e não é um SLA contratado.

## Atualizações e rollback

Antes de atualizar, faça backup, revise dependências e gere as imagens. A CI executa testes, compilação, auditoria de dependências e validação Terraform. Atualizações de schema exigem migração Alembic nova; não altere a migração inicial já aplicada. Para rollback de aplicação, use a imagem anterior somente se compatível com o schema. Prefira restauração em banco separado para mudanças incompatíveis.

Senhas, `.env`, volumes e dados de avaliação não devem ser versionados. Para uma operação externa, defina TLS e `JURIS_COOKIE_SECURE=true`; a aplicação rejeita `environment=production` com cookies inseguros. Ajuste origens para os endereços exatos da aplicação.

## Repetir os smokes locais

`python scripts/verify_http.py` usa uma conta temporária para verificar a aplicação completa em execução. `python scripts/run_load_smoke.py` executa vinte segundos de leitura com cinco usuários e registra CSVs em `reports/`. Ambos removem suas contas de teste; o primeiro preserva a conta se houver tarefa ainda ativa para não apagar registros em processamento. Nenhum dos scripts aprova fontes no banco principal.
