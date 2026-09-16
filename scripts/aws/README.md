# Infraestrutura AWS — Financial Risk & Fraud Analytics Platform

Este diretório contém os scripts usados para provisionar e validar a primeira
parte da plataforma analítica de fraude na AWS. A infraestrutura foi criada com
Python e `boto3`, priorizando reprodutibilidade, segurança, baixo custo e clareza
das decisões técnicas.

Última revisão: 16 de setembro de 2026.

## Arquitetura implementada

```text
PaySim CSV local
    |
    v
Amazon S3
financial-risk-platform/raw/paysim/
    |
    v
AWS Glue Crawler
    |
    v
Glue Data Catalog
financial_risk_raw.raw_paysim
    |
    v
Amazon Athena Workgroup
financial-risk-platform
    |
    v
SQL de validação e, posteriormente, dbt-athena
```

O bucket usado pelo projeto já existia. Para evitar misturar objetos com outros
projetos, todos os dados e resultados desta plataforma ficam abaixo do prefixo:

```text
financial-risk-platform/
├── raw/
│   └── paysim/
├── processed/          # reservado para Parquet e transformações futuras
└── athena-results/
```

No S3, esses diretórios são prefixos de chaves, não pastas reais. Por isso não
foram criados objetos vazios para representá-los.

## Por que boto3

O `boto3` foi escolhido em vez de configurar os recursos apenas pelo console
porque ele permite:

- reproduzir a infraestrutura em outra conta;
- versionar as decisões de configuração;
- tratar erros de forma explícita;
- tornar as operações idempotentes;
- aplicar tags e configurações de segurança de modo consistente;
- demonstrar conhecimento programático dos serviços AWS.

Esses scripts não substituem uma ferramenta de Infrastructure as Code completa,
como Terraform ou AWS CDK. Para este projeto de estudo, eles deixam as chamadas
AWS visíveis e ajudam a aprender as APIs de cada serviço.

## Pré-requisitos

- Python 3.12;
- projeto gerenciado com UV;
- dependências `boto3` e `python-dotenv`;
- uma identidade AWS que não seja a conta root;
- permissões para os serviços utilizados;
- dataset PaySim disponível localmente.

Instalação das dependências:

```bash
uv add boto3 python-dotenv
```

## Variáveis de ambiente

Os scripts carregam um arquivo `.env` com `python-dotenv`:

```dotenv
AWS_ACCESS_KEY_ID=<não-versionar>
AWS_SECRET_ACCESS_KEY=<não-versionar>
AWS_DEFAULT_REGION=<região-do-projeto>
BUCKET_NAME=<nome-globalmente-unico-ou-bucket-existente>
BUDGET_EMAIL=<email-para-alertas>
MONTHLY_BUDGET_USD=5
```

O `.env` deve estar ignorado pelo Git e acessível apenas ao usuário local:

```bash
chmod 600 .env
git check-ignore -v .env
```

Nunca registre chaves em código, documentação, commits, notebooks ou capturas de
tela. Em um ambiente corporativo, devem ser preferidas credenciais temporárias,
IAM Identity Center ou roles associadas ao ambiente de execução. O boto3 suporta
uma [cadeia de provedores de credenciais](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html).

## Inventário dos scripts

| Ordem | Script | Responsabilidade | Gera custo direto? |
|---:|---|---|---|
| 1 | `../check_aws_connection.py` | Valida região e identidade pelo STS | Não |
| 2 | `create_budget.py` | Cria orçamento mensal e alertas | Não, sem ações automáticas |
| 3 | `create_s3_bucket.py` | Cria ou protege o bucket | Armazenamento e requisições posteriores |
| 4 | `../../ingestion/upload_raw_to_s3.py` | Envia o CSV PaySim | Armazenamento e requisições S3 |
| 5 | `create_glue_crawler_role.py` | Cria a role assumida pelo Glue | Não |
| 6 | `create_glue_crawler.py` | Cria database e crawler | Não enquanto o crawler não roda |
| 7 | `run_glue_crawler.py` | Executa e monitora o crawler | Sim |
| 8 | `create_athena_workgroup.py` | Cria workgroup com controles de custo | Não |
| 9 | `run_athena_query.py` | Executa SQL e mede bytes/tempo/custo | Sim |

Os comandos devem ser executados a partir da raiz do repositório.

## 1. Validação da identidade AWS

O primeiro teste usa o AWS Security Token Service para descobrir qual identidade
está assinando as requisições:

```python
session = boto3.Session()
identity = session.client("sts").get_caller_identity()
```

O script imprime apenas a região e o tipo de principal. Se o tipo for `root`, o
processo deve ser interrompido e substituído por um usuário ou role IAM.

Execução:

```bash
uv run scripts/check_aws_connection.py
```

## 2. Proteção de custos com AWS Budgets

Antes de criar recursos, `create_budget.py` configura um orçamento mensal em USD
com dois alertas:

- gasto real acima de 50%;
- gasto previsto acima de 80%.

Trecho principal:

```python
budgets.create_budget(
    AccountId=account_id,
    Budget=budget_config,
    NotificationsWithSubscribers=notifications,
)
```

O orçamento é uma proteção de observabilidade, não um hard limit. Ele envia
alertas, mas não desliga automaticamente S3, Glue ou Athena. Budgets sem ações
são gratuitos; ações automáticas exigiriam IAM adicional e foram evitadas neste
projeto. Consulte o [AWS Budgets FAQ](https://aws.amazon.com/aws-cost-management/aws-budgets/faqs/).

O erro `DuplicateRecordException` é tratado como indicação de que o orçamento já
existe, evitando a criação repetida.

Execução:

```bash
uv run scripts/aws/create_budget.py
```

## 3. Bucket S3

O script `create_s3_bucket.py` cria o bucket quando necessário e reaplica as
configurações de segurança quando ele já pertence à conta.

### Diferença de criação em us-east-1

Para `us-east-1`, `CreateBucketConfiguration` deve ser omitido. Nas demais
regiões, o `LocationConstraint` é enviado:

```python
parameters = {
    "Bucket": bucket_name,
    "ObjectOwnership": "BucketOwnerEnforced",
}

if region != "us-east-1":
    parameters["CreateBucketConfiguration"] = {
        "LocationConstraint": region,
    }
```

### Controles aplicados

- `BucketOwnerEnforced`: desabilita o uso de ACLs para controle de propriedade;
- todos os quatro controles de Block Public Access;
- criptografia padrão SSE-S3 (`AES256`);
- versionamento;
- tags de projeto, ambiente e ferramenta de gerenciamento.

Exemplo do bloqueio público:

```python
s3.put_public_access_block(
    Bucket=bucket_name,
    PublicAccessBlockConfiguration={
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    },
)
```

O S3 já bloqueia acesso público e aplica SSE-S3 por padrão em buckets novos. As
configurações continuam explícitas no script para documentar a intenção e evitar
drift. SSE-S3 foi preferido a SSE-KMS porque não há requisito de chave dedicada e
porque ele evita custos e permissões adicionais de KMS.

O versionamento protege contra sobrescritas e exclusões acidentais, mas versões
antigas também ocupam armazenamento. Por isso os scripts de upload evitam
sobrescrever objetos automaticamente.

Referências:

- [S3 Block Public Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [Criptografia padrão do S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html)
- [API `create_bucket`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/create_bucket.html)

Execução:

```bash
uv run scripts/aws/create_s3_bucket.py
```

## 4. Upload da camada RAW

O CSV é armazenado em:

```text
s3://<bucket>/financial-risk-platform/raw/paysim/PS_20174392719_1491204439457_log.csv
```

O upload usa `TransferConfig` para dividir o arquivo em partes de 64 MiB e enviar
até quatro partes concorrentemente:

```python
transfer_config = TransferConfig(
    multipart_threshold=64 * 1024 * 1024,
    multipart_chunksize=64 * 1024 * 1024,
    max_concurrency=4,
)
```

Metadados registram dataset, camada e origem. O upload também solicita SHA-256
para que o S3 valide a integridade durante a transferência.

Antes de enviar, o script chama `head_object`:

- objeto inexistente: realiza o upload;
- mesmo tamanho: considera o upload já concluído e não cria nova versão;
- tamanho diferente: interrompe em vez de sobrescrever.

Após o envio, o tamanho remoto é comparado com o tamanho local. O `ETag` não é
usado como MD5 porque uploads multipart não garantem essa equivalência. Consulte
[multipart upload no S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html).

Execução:

```bash
uv run ingestion/upload_raw_to_s3.py
```

## 5. IAM role do Glue Crawler

O Glue Crawler não usa diretamente as credenciais locais. Ele assume a role:

```text
AWSGlueServiceRole-FinancialRiskCrawler
```

A trust policy permite somente ao serviço Glue assumir a role:

```json
{
  "Effect": "Allow",
  "Principal": {"Service": "glue.amazonaws.com"},
  "Action": "sts:AssumeRole"
}
```

A política gerenciada `AWSGlueServiceRole` fornece as permissões operacionais do
serviço. Uma política inline separada restringe o S3 a:

- consultar a região do bucket;
- listar somente `financial-risk-platform/raw/*`;
- ler somente objetos abaixo desse prefixo.

`s3:GetBucketLocation` e `s3:ListBucket` ficam em statements diferentes porque a
condição `s3:prefix` é pertinente ao `ListBucket`, não ao `GetBucketLocation`.

O script também reaplica a trust policy quando a role já existe. Isso torna a
configuração repetível e evita confiar que uma role existente permaneceu correta.

O principal que cria o crawler precisa de `iam:PassRole` limitado a essa role.
Não deve receber `iam:PassRole` irrestrito.

Referência: [pré-requisitos de crawler](https://docs.aws.amazon.com/glue/latest/dg/crawler-prereqs.html).

Execução:

```bash
uv run scripts/aws/create_glue_crawler_role.py
```

## 6. Glue Database e Crawler

`create_glue_crawler.py` cria ou atualiza:

```text
Database: financial_risk_raw
Crawler:  financial-risk-paysim-raw-crawler
Alvo:     s3://<bucket>/financial-risk-platform/raw/paysim/
```

O crawler recebe o prefixo `raw_`, por isso a tabela inferida é `raw_paysim`.
Posteriormente, o dbt poderá apresentar essa tabela com o nome lógico
`transactions_raw` usando `identifier: raw_paysim` em um `source`.

Política de mudança de schema:

```python
"SchemaChangePolicy": {
    "UpdateBehavior": "UPDATE_IN_DATABASE",
    "DeleteBehavior": "LOG",
}
```

Alterações detectadas são atualizadas no catálogo, enquanto exclusões são apenas
registradas. Isso reduz o risco de uma execução apagar metadados inesperadamente.

O script configura o crawler, mas deliberadamente não o inicia. Separar criação
e execução evita gerar custo durante testes de infraestrutura.

Execução:

```bash
uv run scripts/aws/create_glue_crawler.py
```

## 7. Execução monitorada do Crawler

`run_glue_crawler.py` inicia a primeira execução, consulta o estado a cada 15
segundos e usa timeout de 15 minutos.

Estados relevantes:

```text
READY -> RUNNING -> READY
```

Ao terminar, `LastCrawl.Status` deve ser `SUCCEEDED`. Se já houver uma execução
anterior, o script não inicia outra automaticamente. Essa decisão evita custo
duplicado por um comando repetido acidentalmente.

O primeiro crawl produziu:

```text
Database:      financial_risk_raw
Table:         raw_paysim
Classification: csv
Header:        skip.header.line.count = 1
```

O crawler inferiu `oldbalancedest` e `newbalancedest` como `string`, embora os
campos representem valores numéricos. A tabela RAW foi mantida como inferida. A
camada staging do dbt fará conversões explícitas com `TRY_CAST` e testes de
qualidade, preservando a separação entre dado bruto e dado confiável.

O `recordCount` produzido pelo crawler é uma estimativa de amostragem e não deve
ser tratado como contagem exata. A contagem oficial será feita pelo Athena.

Execução:

```bash
uv run scripts/aws/run_glue_crawler.py
```

Glue Crawlers são cobrados pelo tempo de processamento. O Data Catalog possui
franquia para até um milhão de objetos de metadados. Consulte os
[preços do AWS Glue](https://aws.amazon.com/glue/pricing/).

## 8. Workgroup do Athena

O workgroup `financial-risk-platform` isola as consultas do projeto e força:

- resultados em `financial-risk-platform/athena-results/`;
- criptografia SSE-S3;
- validação do proprietário esperado do bucket;
- Athena Engine 3;
- limite de 1 GiB examinado por consulta;
- configurações do workgroup sobrepondo configurações do cliente;
- Requester Pays desabilitado.

Trecho do controle de custo:

```python
configuration = {
    "EnforceWorkGroupConfiguration": True,
    "BytesScannedCutoffPerQuery": 1024**3,
    "RequesterPaysEnabled": False,
}
```

O limite de 1 GiB permite uma leitura completa do CSV de aproximadamente 471 MiB,
mas bloqueia consultas acidentalmente maiores. Esse limite poderá ser reavaliado
quando os modelos dbt fizerem joins; o uso de Parquet reduzirá significativamente
os bytes examinados.

`list_work_groups` retorna `NextToken`, mas não possui paginator registrado na
versão usada do botocore. A paginação foi implementada manualmente:

```python
while True:
    response = athena.list_work_groups(**request)
    next_token = response.get("NextToken")
    if next_token is None:
        break
```

Execução:

```bash
uv run scripts/aws/create_athena_workgroup.py
```

Referência: [workgroups do Athena](https://docs.aws.amazon.com/athena/latest/ug/creating-workgroups.html).

## 9. Consulta de validação no Athena

`run_athena_query.py` executa uma agregação sobre a tabela RAW:

```sql
SELECT
    COUNT(*) AS total_transactions,
    MIN(step) AS first_step,
    MAX(step) AS last_step,
    SUM(CASE WHEN isfraud = 1 THEN 1 ELSE 0 END)
        AS fraud_transactions,
    ROUND(
        100.0 * SUM(CASE WHEN isfraud = 1 THEN 1 ELSE 0 END)
        / COUNT(*),
        4
    ) AS fraud_rate_pct
FROM financial_risk_raw.raw_paysim
```

Resultados esperados:

| Métrica | Valor |
|---|---:|
| Total de transações | 6.362.620 |
| Primeiro step | 1 |
| Último step | 743 |
| Transações fraudulentas | 8.213 |
| Taxa de fraude | 0,1291% |

O script usa um `ClientRequestToken` fixo. Repetir exatamente a mesma solicitação
retorna o mesmo `QueryExecutionId`, evitando uma nova consulta cobrada.

O polling acontece a cada dois segundos, com timeout de cinco minutos. Ao atingir
o timeout, `stop_query_execution` é chamado para cancelar a consulta.

Além do resultado, são registrados:

- `DataScannedInBytes`;
- `EngineExecutionTimeInMillis`;
- `TotalExecutionTimeInMillis`;
- custo estimado.

Estimativa usada:

```python
estimated_cost = bytes_scanned / 10**12 * 5.0
```

O Athena cobra por bytes examinados, com mínimo de 10 MB por consulta. Arquivos
CSV exigem leitura do arquivo inteiro mesmo quando poucas colunas são selecionadas.
Esse comportamento será usado como baseline para comparar CSV e Parquet.

Execução:

```bash
uv run scripts/aws/run_athena_query.py
```

Referência: [preços do Athena](https://aws.amazon.com/athena/pricing/).

## Idempotência

As operações foram desenhadas para que uma nova execução seja previsível:

| Recurso | Estratégia |
|---|---|
| Budget | Trata `DuplicateRecordException` |
| Bucket | Lista buckets próprios antes de criar e reaplica segurança |
| Upload | Verifica existência e tamanho antes de enviar |
| IAM role | Consulta antes de criar e reaplica trust/policies |
| Glue Database | Cria quando ausente e atualiza quando existente |
| Glue Crawler | Cria quando ausente e atualiza quando existente |
| Execução do crawler | Não repete se já houver `LastCrawl` |
| Athena Workgroup | Lista antes de criar |
| Consulta Athena | Usa `ClientRequestToken` fixo |

Idempotência não significa que todo script é livre de efeitos. Ela significa que
o efeito de uma repetição foi pensado e controlado.

## Segurança e permissões

Princípios aplicados:

- nenhuma credencial é versionada;
- conta root não é usada;
- bucket sem acesso público;
- ACLs desabilitadas;
- criptografia em repouso;
- política do crawler limitada ao prefixo RAW;
- `iam:PassRole` deve ser limitado à role do crawler;
- validação do proprietário do bucket nos resultados do Athena;
- tags para rastrear propriedade e ambiente.

Permissões de alto nível necessárias para o principal que executa os scripts:

```text
sts:GetCallerIdentity
budgets:CreateBudget
s3:CreateBucket e operações de configuração/upload usadas
iam:GetRole/CreateRole/UpdateAssumeRolePolicy/AttachRolePolicy/PutRolePolicy
iam:PassRole na role específica do crawler
glue:Get/Create/Update Database e Crawler
glue:StartCrawler/GetCrawler/GetTables
athena:List/Create WorkGroup
athena:Start/Get/Stop QueryExecution e GetQueryResults
```

Essa lista descreve ações utilizadas, não uma política IAM pronta. Uma política
real deve limitar recursos e condições conforme a conta e a região.

## Custos e controles

Principais fontes de custo:

- armazenamento e requisições do S3;
- execução do Glue Crawler;
- bytes examinados pelo Athena;
- futuras transformações Glue ou dbt/Athena.

Controles existentes:

- orçamento mensal com alertas;
- crawler iniciado separadamente da criação;
- prevenção de recrawl acidental;
- cutoff de 1 GiB por consulta Athena;
- token idempotente na consulta de baseline;
- objeto RAW sem sobrescrita automática;
- SSE-S3 em vez de KMS dedicado.

Entrada de dados da internet para o S3 não possui tarifa de transferência padrão,
mas armazenamento e requisições continuam cobrados. Valores variam por região;
consulte sempre as páginas oficiais de preço.

## Troubleshooting

### `AccessDenied` em `create_crawler`

Verifique se o principal local possui `iam:PassRole` para
`AWSGlueServiceRole-FinancialRiskCrawler`, além das permissões Glue necessárias.

### `BucketAlreadyExists`

Nomes de bucket são globais. Defina outro `BUCKET_NAME`. Não continue tentando
configurar um bucket que pertence a outra conta.

### `OperationNotPageableError: list_work_groups`

Não use `get_paginator("list_work_groups")` nessa versão do botocore. O script
implementa paginação manual com `NextToken`.

### Crawler terminou, mas não criou tabela

Confirme:

- path S3 do target;
- existência do objeto CSV;
- trust policy com `glue.amazonaws.com`;
- `s3:ListBucket` e `s3:GetObject` no prefixo correto;
- status e `ErrorMessage` de `LastCrawl`.

### Tipos incorretos no catálogo

O crawler infere tipos por amostragem. A camada RAW pode manter tipos permissivos;
o dbt staging deve aplicar casts explícitos e testes. Não confie na inferência do
crawler como contrato definitivo de dados.

### Query excedeu 1 GiB

O workgroup interrompeu uma consulta acima do cutoff. Verifique scans repetidos,
joins, ausência de filtros e formato CSV. Prefira Parquet particionado antes de
aumentar o limite.

## Limpeza dos recursos

Quando o projeto não for mais necessário, remova os recursos na ordem inversa:

1. resultados e dados do projeto no S3;
2. versões antigas e delete markers, pois o bucket tem versionamento;
3. Athena workgroup;
4. Glue Crawler;
5. tabelas e Glue Database;
6. política inline e política gerenciada da role;
7. IAM role;
8. budget, se não for mais útil;
9. bucket somente se ele não for compartilhado com outros projetos.

O bucket atual já existia antes desta plataforma. Portanto, não deve ser apagado
como parte de um cleanup automático sem confirmar que não contém dados externos ao
prefixo `financial-risk-platform/`.

## Próxima etapa

Com S3, Glue e Athena validados, a próxima fase é configurar `dbt-athena`:

1. instalar o adapter;
2. criar o projeto dbt;
3. configurar `profiles.yml` sem credenciais versionadas;
4. declarar `financial_risk_raw.raw_paysim` como source;
5. criar `stg_transactions` com renomeação e casts explícitos;
6. adicionar testes de `not_null`, `accepted_values` e testes customizados;
7. gerar documentação e lineage com `dbt docs`.

