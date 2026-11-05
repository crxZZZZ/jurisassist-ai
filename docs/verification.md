# Verificação da entrega — 23/10/2026

Ambiente: Windows, Python 3.12, 16 GiB de RAM e NVIDIA RTX 3060 Ti com 8 GiB. Aplicação executada por Docker Desktop/WSL2; inferência no Ollama do host e embeddings ONNX em CPU. A imagem da interface usa Node.js 22.

## Verificações concluídas

| Verificação | Resultado |
|---|---|
| Backend, incluindo banco PostgreSQL descartável | **31 testes aprovados**, incluindo recuperação do modelo sem duplicar respostas |
| Ruff, incluindo scripts e migrações | Aprovado |
| Compilação TypeScript/Vite e imagens Docker | Aprovadas |
| Playwright, desktop e celular | **6 jornadas aprovadas**; capturas conferidas |
| HTTP real no Compose | Login, CSRF, status do modelo, fila, SSE, indexação ONNX e logout aprovados |
| Terraform | `fmt -check` e `validate` aprovados; nenhum `apply` executado |
| Auditoria Python fixada | Nenhuma vulnerabilidade conhecida encontrada na execução de pip-audit |
| Dependências de execução da interface | npm audit sem vulnerabilidades conhecidas |
| Backup/restauração | SHA-256 conferido; três documentos públicos recuperados em banco separado |

O backup restaurado continha fontes pendentes de aprovação: três documentos, nenhum trecho indexado e nenhum usuário. O banco principal foi preservado. A integridade de vetores e a concorrência da fila foram testadas separadamente no PostgreSQL descartável. A CI está configurada, mas não foi executada no GitHub nesta sessão.

## Recuperação de fontes

O conjunto versionado tem 80 cenários. A matriz sem geração executou os **55 casos com artigo esperado**, usando os mesmos snapshots; os outros 25 ficaram apenas inventariados.

| Recuperador | Acertos entre os 5 primeiros | Recall@5 |
|---|---:|---:|
| Textual: PostgreSQL + BM25 em português | 45/55 | 81,82% |
| Vetorial: E5 small + pgvector | 46/55 | 83,64% |
| Híbrido: fusão ponderada e diversidade de artigos | **50/55** | **90,91%** |

A meta de recuperação de 90% foi atingida. O relatório híbrido v2 registrou p50 de 157 ms e p95 de 274 ms nesta execução, com outros processos de teste ativos. Isso mede recuperação, não geração de respostas ou precisão jurídica.

Os [relatórios completos](evidence/retrieval-hybrid-v2.json) incluem os casos, hashes dos documentos e prompts, revisão do artefato de embeddings e parâmetros. As variantes v1/v2 têm o mesmo Recall porque prompts não participam do recuperador. Houve iteração sobre esse conjunto de desenvolvimento; não é uma avaliação independente de generalização.

## Inferência real e ferramentas

Foi executada uma [amostra de quatro perguntas com cada prompt](evidence/model-chat-comparison.json), totalizando oito fluxos. As consultas gerais sobre empregador e responsabilidade na terceirização retornaram respostas com citações existentes. A pergunta histórica retornou limite explícito.

A [primeira comparação](evidence/model-chat-before-intent-gate.json) revelou uma falha: o prompt v2 aceitou no texto um pedido para inventar uma referência, associando-o a IDs de fontes existentes. Isso demonstrou a diferença entre integridade referencial e fundamentação semântica. Foi acrescentada uma classificação estruturada de intenção antes da pesquisa, com teste de regressão que impede pedidos fora do escopo de alcançar ferramentas. Na repetição real, ambas as variantes recusaram o pedido, sem citações e sem reproduzir o marcador inventado, em aproximadamente 2,7 segundos. A verificação não equivale a uma bateria abrangente de ataques.

A consulta sobre empregador acionou uma ferramenta selecionada pelo modelo em ambas as versões. Nas outras consultas dessa amostra, o recuperador inicial foi suficiente e não houve chamada adicional. Fluxos com geração levaram aproximadamente 27–40 segundos; a primeira execução inclui carregamento e não deve ser comparada diretamente às seguintes como ganho de prompt.

A [análise real do contrato fictício](evidence/model-contract-smoke.json) processou dois de dois trechos, gerou quatro pontos de atenção e sete referências, em 31,32 segundos. As citações literais foram resolvidas pelo servidor a partir do documento original. Obrigações, prazos e pontos passaram pela validação de referências.

Os testes rápidos usam doubles explícitos; os arquivos acima registram a inferência real. **Não foi executada a matriz inteira de 80 casos com geração**, nem concluída revisão jurídica humana. Não há percentual de precisão jurídica certificado.

## Carga limitada da API

Locust executou leitura autenticada com cinco usuários simultâneos por vinte segundos, enquanto a comparação dos prompts também estava em andamento. Foram observadas aproximadamente vinte requisições por segundo e nenhuma falha. A última [amostra CSV](evidence/api-load_stats.csv) registrou 365 requisições; a listagem de documentos teve p50 de 30 ms e p95 de 84 ms.

Esse teste cobre leitura da API e autenticação, com uma base pequena e sem geração em cada requisição. Não mede a capacidade máxima da GPU, concorrência de inferência, alta disponibilidade ou desempenho na AWS. O worker continua limitado por padrão a um processo.

## Capturas e primeiro acesso

As capturas [desktop](evidence/ui-chromium.png) e [celular](evidence/ui-mobile.png) usam fixtures de interface identificadas, com dados fictícios. A execução real do Compose está em `http://localhost:8080`.

Não existe conta ou senha padrão. Crie seu administrador com `powershell -ExecutionPolicy Bypass -File scripts/create-user.ps1`. Após entrar, revise e aprove os três snapshots em Administração para habilitar a pesquisa. A revisão é uma etapa de operação do produto; os snapshots do benchmark foram usados apenas como fixtures técnicas em banco separado.
