# Snapshots públicos para primeira execução

Os JSONs contêm somente texto e trechos de legislação do Planalto, coletados em 23/10/2026. Cada arquivo registra URL, data real de coleta, checksum e revisão do parser. Não há dados da empresa ou de usuários.

`jurisassist init-sources` importa esses snapshots somente quando a fonte ainda não tem documentos. Eles ficam **pendentes de revisão**, sem aprovação ou indexação automática. Isso permite preparar a demonstração mesmo quando o Planalto bloqueia conexões do container. A verificação diária tenta obter novas versões pela URL oficial e preserva a base anterior em caso de falha.

Os snapshots não garantem vigência, completude ou adequação ao caso. Confira as notas de alteração antes de aprovar. Atualizações posteriores são armazenadas no banco e não reescrevem os arquivos do repositório. Para reproduzir um benchmark, registre os checksums do relatório.
