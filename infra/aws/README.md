# AWS de referência — nenhuma implantação executada

Este módulo descreve uma implantação inicial de nó único: EC2 com GPU, rede dedicada, EBS criptografado, IMDSv2, acesso administrativo por SSM e bucket S3 privado com TLS obrigatório, criptografia, versionamento e expiração de backups. Não oferece alta disponibilidade. Terraform `validate` não comprova disponibilidade regional, quota de GPU ou funcionamento do software na AMI escolhida.

```bash
terraform fmt -check -recursive infra
terraform -chdir=infra/aws init -backend=false
terraform -chdir=infra/aws validate
```

Esses comandos validam a configuração e baixam o provider; não precisam criar recursos AWS. **Nenhum workflow executa `apply`.** Uma implantação futura precisa de orçamento e credenciais próprios. EC2 com GPU, EBS, IPv4 público e S3 podem gerar cobrança; não é uma implantação gratuita.

## Acesso e bootstrap futuro

A AMI é uma entrada obrigatória. Prepare e revise uma imagem Ubuntu com driver NVIDIA, Docker/Compose, AWS CLI, agente SSM e Ollama. O módulo não escolhe automaticamente uma AMI de terceiros nem executa código remoto por `user_data`. `terraform.example.tfvars` contém um identificador ilustrativo e não deve ser usado para implantar.

A EC2 tem IPv4 público para saída HTTPS a SSM e registros de imagens, mas nenhuma regra de entrada. Não há SSH público, load balancer ou hostname público. Encaminhe a porta 8080 por SSM para uma sessão administrativa de avaliação. Use a configuração local por esse túnel; antes de qualquer serviço público real, implemente TLS, cookies seguros e origens adequadas.

Depois de uma futura criação autorizada, transfira um release revisado via SSM/S3, crie `.env` com credenciais próprias, vincule o Ollama somente à interface necessária à rede dos containers, execute Compose, crie um usuário e prepare as fontes. Não copie credenciais do computador de desenvolvimento para a nuvem.

O IAM da instância permite operações de SSM e `GetObject`/`PutObject` somente em `database/*` do bucket criado. Backups precisam ser executados e enviados explicitamente, por exemplo via tarefa agendada com AWS CLI e role da instância; a política S3, isoladamente, não agenda backups. O volume raiz é preservado após término da instância e deve entrar no inventário de custos e descarte.

## Evolução para escala

Separar API em ECS, inferência em serviço GPU privado e PostgreSQL em banco gerenciado com pgvector. Usar armazenamento de objetos para artefatos, HTTPS e identidade corporativa; adicionar coleta consolidada de métricas, alertas, filas particionadas, testes de carga e validação de recuperação. Aumentar workers somente junto à capacidade do serviço de inferência.

A arquitetura implementada permite separar processos, mas capacidade, disponibilidade e custos dessa evolução não foram medidos.
