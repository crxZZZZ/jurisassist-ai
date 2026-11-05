# Avaliação e experimentos

O conjunto `evaluation/cases.jsonl` possui 80 cenários: 40 pesquisas legais, 15 contratos sintéticos, 15 perguntas sem suporte ou ambíguas e 10 tentativas adversariais. Os casos jurídicos e contratuais têm fonte e artigo esperados para recuperação. Esses rótulos são referências iniciais de engenharia, sem certificação por advogado.

## Execução

```bash
jurisassist evaluate --matrix
jurisassist evaluate --matrix --generate
```

Sem geração, são avaliados 55 casos de recuperação e inventariados os outros 25; estes últimos não têm aprovação automática de comportamento. `inventory_cases` indica o inventário, `evaluated` os casos efetivamente executados, `retrieval_cases` o denominador de Recall@5 e `generation_cases` quantos passaram pelo modelo. Latências excluem os casos apenas inventariados. Dois prompts não modificam o recuperador: diferenças de qualidade de prompt só podem ser interpretadas quando `generation=true`.

A execução exige as três fontes indexadas. Documentos temporários são criados em uma transação e revertidos ao terminar. Relatórios JSON ficam em `data/evaluations` ou no volume Docker equivalente e aparecem no painel administrativo. Parâmetros, modelos, duração e IDs recuperados são registrados.

Meta: pelo menos 90% de Recall@5 nos casos de recuperação. Citações publicadas devem corresponder a trechos autorizados existentes; isso é uma propriedade estrutural testada separadamente da precisão jurídica.

## Rubrica humana

Para cada resultado com geração, um revisor deve registrar de zero a dois em: correção, suporte das afirmações, completude, adequação ao escopo e clareza. Zero significa falha, um significa parcialmente atendido, dois significa atendido. Registre as afirmações sem suporte e fontes faltantes. Não publique um percentual de precisão jurídica enquanto essa revisão não tiver sido feita.

Perguntas ambíguas devem gerar esclarecimento ou declaração de limite; perguntas fora da base não devem ser respondidas a partir da memória do modelo. Casos adversariais verificam ausência de marcadores proibidos e integridade de citações. Esses testes são sinais de regressão, não uma prova de resistência a toda prompt injection. Testes de autorização e ferramentas também exercitam acesso negado independentemente do LLM.

## Método experimental

Compare textual, vetorial e híbrido usando o mesmo snapshot. Compare v1 e v2 mantendo modelo e parâmetros fixos. Registre mudanças de código e checksum dos documentos ao interpretar resultados. Use falhas do conjunto de desenvolvimento para ajustar a busca; mantenha novos casos separados para avaliar generalização, evitando otimização baseada somente nas perguntas conhecidas.

Latências de execução com geração incluem ferramentas e modelo; latências sem geração medem principalmente recuperação. A primeira execução inclui carregamento de embeddings. Warmup e concorrência devem ser documentados em medições de capacidade. Não generalize um resultado local para produção em nuvem.
