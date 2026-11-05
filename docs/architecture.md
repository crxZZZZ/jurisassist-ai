# Decisões arquiteturais

## ADR 001 — Monólito modular e processos separados

FastAPI cuida de autenticação, autorização, validação e submissão. O worker executa tarefas de IA e ingestão. PostgreSQL é a fonte de verdade de ambos. Evita-se Redis e uma plataforma de agentes gerenciada para reduzir infraestrutura e custos locais.

Cada tarefa possui lease de dez minutos, renovado a cada vinte segundos, no máximo três tentativas e token de propriedade. O claim usa `FOR UPDATE SKIP LOCKED`. A publicação final é feita em transação e confere o token sob bloqueio. Em uma interrupção, o próximo worker recupera a tarefa após expirar o lease. Embeddings e resultados só passam a disponíveis após commit. Mensagem, análise e conclusão da tarefa são persistidas juntas. Falhas de coleta não substituem o corpus aprovado.

O checkpoint é a tarefa inteira; não há recuperação intermediária de um lote de análise ou nó do grafo. Uma repetição pode consumir inferência novamente. Esse custo é aceitável na primeira versão local, e fica explícito para uma evolução com checkpoints PostgreSQL do LangGraph.

## ADR 002 — Inferência local e orçamento

Qwen3 4B Q4 por Ollama usa a GPU do host. E5 small quantizado em ONNX Runtime usa dois threads de CPU, vetores normalizados de 384 dimensões e prefixos `query:` / `passage:`. Tokenização, pooling por máscara de atenção e normalização são explícitos. A revisão do artefato é fixada e o cache é consultado primeiro para permitir operação offline. O caminho de inferência é apenas de texto, evitando bibliotecas de imagens desnecessárias. Não há fallback para API paga nem resposta simulada no produto.

O contexto de 8.192 tokens, temperatura zero, máximo de 2.200 tokens de saída e recuperação limitada ajudam a conter memória e duração. Contratos de até 180 mil caracteres são processados por lotes de seis trechos de aproximadamente mil caracteres; todos os lotes precisam passar na validação antes da publicação. A cobertura é registrada. O limite de trinta minutos impede análise indefinida.

## ADR 003 — RAG e referências

A busca usa candidatos full text PostgreSQL em português, ranking BM25 com stemming e distância cosseno pgvector, fundidos por Reciprocal Rank Fusion ponderado. Índices GIN e HNSW são criados pela migração. Os resultados priorizam diversidade de artigos. Filtros de autorização e versão são aplicados antes da recuperação. Artigos e parágrafos são preservados como localizadores; fragmentos longos são divididos para a janela dos embeddings.

O índice BM25 mantém cache limitado a quatro corpora autorizados e é adequado à base inicial pequena. Para coleções muito maiores, substituí-lo por um serviço de busca externo ou extensão BM25 evita carregar o corpus textual no processo. A busca vetorial permanece no PostgreSQL.

O grafo tem delimitação, pesquisa, elaboração e validação. A delimitação combina limites determinísticos de cobertura com um classificador estruturado de intenção, antes de recuperar fontes ou chamar ferramentas. Pedidos fora do escopo encerram o fluxo sem pesquisa; fatos essenciais ausentes podem gerar perguntas de esclarecimento. O prompt desse classificador é versionado separadamente.

Chamadas de ferramentas adicionais são escolhidas pelo modelo, mas somente três chamadas de uma lista fixa são executadas. Argumentos têm schemas restritos. Ferramentas não permitem URLs arbitrárias, SQL, shell ou arquivos locais. Recuperação inicial é determinística; mensagens anteriores não viram evidência.

Uma resposta jurídica exige afirmações com IDs de evidências recuperadas. Os schemas enviados ao Ollama enumeram os IDs permitidos. O backend resolve citações, URLs, versão e trechos. Uma referência inválida permite uma correção; se falhar novamente, a resposta informa evidência insuficiente. Em contratos, o servidor preenche a citação literal diretamente do trecho selecionado, e valida novamente a correspondência. Essas regras verificam integridade referencial, e não equivalência semântica: a qualidade da interpretação exige avaliação humana.

## ADR 004 — Corpus e temporalidade

Fontes possuem URLs fixas em allowlist. A coleta suporta proxy do ambiente, exige HTTPS e não segue redirecionamentos. Há limite de oito MB por fonte. Uma mudança no checksum cria versão pendente de revisão. Aprovação enfileira indexação; apenas a conclusão transacional aposenta a versão anterior. Trechos antigos são preservados para citações históricas já emitidas.

O worker verifica fontes vencidas a cada ciclo horário; uma fonte é elegível para nova coleta após 24 horas. Após sete dias sem verificação bem-sucedida, a interface sinaliza a base. Falha de parser ou rede preserva o corpus anterior. Questões de vigência histórica não são resolvidas automaticamente. Textos legais podem conter redações concorrentes e efeitos futuros: revisão administrativa é necessária e registrada.

## ADR 005 — Segurança e privacidade

Sessões aleatórias são armazenadas por hash; cookies HttpOnly/SameSite e CSRF vinculado à sessão protegem mutações. Senhas usam Argon2id. Não existe cadastro público ou senha padrão. O banco compartilha contadores de taxa e limita tarefas por usuário. Falhas de autenticação usam hash dummy para reduzir diferenças de tempo.

Usuário e administrador não podem acessar documentos privados de outras contas. O administrador visualiza diagnóstico global de tarefas e feedback. Logs não registram textos de perguntas, contratos, senhas, tokens ou respostas. URLs externas no produto são fontes oficiais resolvidas pelo servidor. HTML/Markdown recebidos são exibidos como texto, sem renderização de HTML bruto.

Logs e métricas são locais; LangSmith e telemetria remota não são ativados. Toda a aplicação deve permanecer vinculada ao loopback no ambiente de demonstração. TLS, política de retenção corporativa, identidade federada e auditoria jurídica precisam de adaptação para uma adoção real.
