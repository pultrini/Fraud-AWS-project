# Financial Risk Platform

Plataforma end-to-end de engenharia de dados, analytics e machine learning para análise de risco e detecção de fraude no dataset sintético PaySim.

O projeto parte de um CSV com 6.362.620 transações, constrói um data lake no Amazon S3, cataloga os dados com AWS Glue, consulta com Athena, transforma com dbt, disponibiliza marts para BI no Apache Superset e treina modelos locais rastreados pelo MLflow. Os datasets versionados e os artefatos dos modelos são persistidos no S3.

## Objetivos

- construir uma arquitetura analítica reproduzível na AWS;
- aplicar modelagem em camadas com dbt;
- validar qualidade, granularidade e consistência dos dados;
- reduzir custo de consulta convertendo CSV em tabelas Parquet;
- criar uma camada local de BI com DuckDB e Superset;
- comparar regras de negócio e modelos de classificação desbalanceada;
- rastrear experimentos, datasets e modelos com MLflow;
- investigar se a estrutura entre contas contém sinal útil para modelos de grafo.

## Arquitetura

```text
PaySim CSV
    |
    v
Amazon S3: raw/paysim
    |
    v
AWS Glue Crawler + Data Catalog
    |
    v
Amazon Athena
    |
    v
dbt-athena
    |
    +--> staging views
    +--> intermediate views
    +--> facts, dimensions and analytical marts in Parquet
              |
              +--> BI snapshot --> DuckDB --> Apache Superset
              |
              +--> ML snapshot --> local training
                                      |
                                      +--> Logistic Regression
                                      +--> Random Forest
                                      +--> XGBoost
                                      |
                                      v
                              MLflow Registry + S3 artifacts
```

O processamento que gera os marts acontece na AWS. Depois da sincronização, BI, EDA e treinamento são executados localmente para evitar novas consultas ao Athena.

## Tecnologias

| Camada | Tecnologias |
|---|---|
| Linguagem e ambiente | Python 3.12, UV |
| Cloud | Amazon S3, AWS Glue, Amazon Athena, AWS Budgets, IAM |
| Infraestrutura programática | boto3 |
| Transformação | dbt Core, dbt-athena, SQL |
| Armazenamento analítico | Parquet, Glue Data Catalog |
| Processamento local | DuckDB, pandas, PyArrow |
| BI | Apache Superset, Docker Compose, DuckDB |
| Machine learning | scikit-learn, XGBoost |
| Experiment tracking | MLflow, SQLite e S3 |

## Dataset e problema

PaySim simula transações financeiras móveis. Cada linha representa uma transação entre uma conta de origem e uma conta de destino, com tipo, valor, saldos e indicadores de fraude.

O conjunto completo possui:

| Métrica | Valor |
|---|---:|
| Transações | 6.362.620 |
| Fraudes | 8.213 |
| Taxa de fraude | 0,1291% |
| Etapas temporais | 1 a 743 |

Como a classe positiva é extremamente rara, acurácia não é usada como métrica principal. A avaliação prioriza average precision, precision, recall, F1, matriz de confusão e quantidade de alertas gerados.

## Modelagem dbt

### Staging

`stg_paysim_transactions` padroniza nomes, tipos, categorias e indicadores booleanos da tabela catalogada pelo crawler.

### Intermediate

- `int_paysim_transactions_enriched`: adiciona tempo simulado, tipos de conta e variações de saldo;
- `int_customer_transaction_features`: cria histórico por cliente usando janelas temporais que não incluem a transação atual.

### Core e dimensões

- `fact_transactions`;
- `dim_customer`;
- `dim_transaction_type`;
- `dim_simulation_day`.

### Marts

- `mart_fraud_by_transaction_type`;
- `mart_fraud_daily`;
- `mart_customer_risk`;
- `mart_transaction_behavior`;
- `mart_fraud_training_features`;
- `mart_fraud_ml_dataset`.

Os modelos materializados no Athena são gravados em Parquet no S3. Os testes dbt verificam valores aceitos, campos obrigatórios, unicidade, preservação de linhas e totais, consistência temporal e presença das duas classes nos splits de ML.

## Divisão temporal para machine learning

O projeto evita uma divisão aleatória, que permitiria misturar passado e futuro:

```text
TRAIN       simulation_step <= 322
VALIDATION  323 <= simulation_step <= 375
TEST        simulation_step > 375
```

Todas as fraudes do período de treino são mantidas. Para reduzir tempo e memória local, apenas 5% das transações legítimas de treino são selecionadas por um hash determinístico do `transaction_id`. Validação e teste permanecem completos.

O threshold de classificação é escolhido exclusivamente na validação pelo maior F1 e depois aplicado sem alteração ao teste.

## Resultados dos modelos

### Experimento principal sem a regra explícita de saldo

As features `amount_to_origin_balance_ratio` e `origin_has_sufficient_balance` foram removidas para evitar que os modelos dependessem diretamente de uma particularidade quase determinística do simulador.

Resultados no teste:

| Modelo | Precision | Recall | F1 | Average precision | Falsos positivos | Falsos negativos |
|---|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 86,07% | 36,56% | 51,32% | 0,6545 | 238 | 2.553 |
| Random Forest | 89,25% | 74,11% | 80,98% | 0,8533 | 359 | 1.042 |
| XGBoost | **91,78%** | **81,81%** | **86,51%** | **0,9266** | **295** | **732** |

O XGBoost é o melhor candidato atual. Na validação, obteve average precision de `0,8258` e F1 de `78,27%`. No teste, encontrou 3.292 das 4.024 fraudes.

### Auditoria do resultado quase perfeito

No primeiro experimento, Random Forest e XGBoost alcançaram resultados próximos de 100%. A investigação mostrou que quase toda fraude do PaySim drena o saldo disponível da origem:

```text
transaction_type in ('TRANSFER', 'CASH_OUT')
and transaction_amount approximately equals origin_balance_before
```

Uma regra simples baseada nessa relação encontrou 551 de 556 fraudes na validação sem falsos positivos. Isso não é vazamento direto do target, porque saldo anterior, tipo e valor estão disponíveis no momento da decisão. Entretanto, é um forte artefato do simulador e não deve ser interpretado como desempenho esperado em produção.

A ablação reduziu o F1 de teste do XGBoost de `99,91%` para `86,51%`, produzindo uma avaliação mais informativa. O número de melhor iteração do XGBoost passou de 5 para 1.073, confirmando que a regra explícita tornava o problema quase trivial.

## EDA do grafo de transações

O grafo foi definido como:

```text
origin_account_id --> destination_account_id
```

Cada conta é um nó e cada transação é uma aresta direcionada. A análise do snapshot completo encontrou:

| Métrica | Valor |
|---|---:|
| Nós | 9.073.900 |
| Arestas | 6.362.620 |
| Pares direcionados únicos | 6.362.620 |
| Pares repetidos | 0 |
| Self-loops | 0 |
| Densidade | 7,73 × 10⁻⁸ |
| Grau total médio | 1,40 |
| Grau total mediano | 1 |
| Nós com grau 1 | 8.604.623 — 94,8% |
| Grau máximo | 113 |

Como quase todos os nós participam de uma única transação e não existem pares repetidos, uma GNN teria pouca vizinhança para message passing. A próxima investigação será uma comparação controlada entre o XGBoost atual e o XGBoost enriquecido com features históricas de grafo. Uma GNN só será priorizada se essas features demonstrarem ganho mensurável.

## Estrutura do repositório

```text
.
├── ingestion/                 # Perfil e upload do CSV bruto
├── scripts/
│   ├── aws/                   # Provisionamento e consultas AWS
│   ├── bi/                    # Sincronização e banco DuckDB para BI
│   └── ml/                    # Datasets, treinamento, MLflow e graph EDA
├── models/
│   ├── staging/               # Limpeza e padronização
│   ├── intermediate/          # Enriquecimento e features históricas
│   └── marts/                 # Fatos, dimensões, BI e ML
├── tests/                     # Testes singulares do dbt
├── macros/                    # Macros SQL reutilizáveis
├── dashboard/superset/        # Superset em Docker
├── docs/                      # Documentação detalhada do dbt
├── data/                      # Dados locais ignorados pelo Git
├── artifacts/                 # Modelos e métricas locais ignorados pelo Git
├── dbt_project.yml
├── profiles.yml
└── pyproject.toml
```

## Pré-requisitos

- Python 3.12;
- [UV](https://docs.astral.sh/uv/);
- Docker e Docker Compose para o Superset;
- conta AWS e identidade IAM com as permissões necessárias;
- dataset PaySim disponível localmente;
- credenciais AWS configuradas por `.env`, perfil ou outra fonte suportada pelo boto3.

Instale o ambiente:

```bash
uv sync
```

## Configuração

Crie `.env` a partir de `.env.example` e preencha os valores do seu ambiente:

```dotenv
AWS_DEFAULT_REGION=us-east-1
BUCKET_NAME=your-bucket-name

S3_PROJECT_PREFIX=financial-risk-platform
ML_DATASET_S3_PREFIX=financial-risk-platform/ml/datasets
MLFLOW_ARTIFACT_S3_PREFIX=financial-risk-platform/mlflow-artifacts

MLFLOW_TRACKING_URI=http://127.0.0.1:5000
MLFLOW_HOST=127.0.0.1
MLFLOW_PORT=5000
MLFLOW_EXPERIMENT_NAME=fraud-detection
MLFLOW_REGISTERED_MODEL_NAME=fraud-detection-classifier
```

Variáveis opcionais para orçamento:

```dotenv
BUDGET_EMAIL=your-email@example.com
MONTHLY_BUDGET_USD=5
```

Nunca versione `.env`, chaves AWS ou secrets do Superset.

## Execução end-to-end

Todos os comandos abaixo partem da raiz do repositório.

### 1. Validar a conexão AWS

```bash
uv run --env-file .env python scripts/check_aws_connection.py
```

### 2. Criar proteções e infraestrutura

```bash
uv run --env-file .env python scripts/aws/create_budget.py
uv run --env-file .env python scripts/aws/create_s3_bucket.py
uv run --env-file .env python scripts/aws/create_glue_crawler_role.py
uv run --env-file .env python scripts/aws/create_glue_crawler.py
uv run --env-file .env python scripts/aws/create_athena_workgroup.py
```

Os scripts são idempotentes: eles verificam o estado atual antes de criar ou atualizar recursos.

### 3. Enviar o PaySim ao S3

Coloque o CSV em `data/raw/` e execute:

```bash
uv run --env-file .env python ingestion/profile_raw.py
uv run --env-file .env python ingestion/upload_raw_to_s3.py
```

### 4. Catalogar os dados brutos

```bash
uv run --env-file .env python scripts/aws/run_glue_crawler.py
```

O crawler cria ou atualiza `financial_risk_raw.raw_paysim` no Glue Data Catalog.

### 5. Validar Athena e dbt

```bash
uv run --env-file .env python scripts/aws/run_athena_query.py

uv run --env-file .env dbt debug \
  --profiles-dir .
```

Compile sem executar:

```bash
uv run --env-file .env dbt compile \
  --profiles-dir .
```

Execute todos os modelos e testes:

```bash
uv run --env-file .env dbt build \
  --profiles-dir .
```

Seletores úteis:

```bash
uv run --env-file .env dbt build \
  --profiles-dir . \
  --selector dashboard_marts

uv run --env-file .env dbt build \
  --profiles-dir . \
  --selector ml_pipeline
```

Compare o scan do CSV bruto com a tabela Parquet:

```bash
uv run --env-file .env python scripts/aws/compare_csv_vs_parquet.py
```

## BI local com DuckDB e Superset

Sincronize os marts do S3 e construa o banco local:

```bash
uv run --env-file .env python scripts/bi/sync_bi_marts.py
uv run python scripts/bi/build_bi_database.py
```

Crie `dashboard/superset/.env` a partir do exemplo:

```dotenv
SUPERSET_SECRET_KEY=replace-with-a-long-random-secret
```

Inicialize o Superset:

```bash
docker compose -f dashboard/superset/docker-compose.yml build

docker compose -f dashboard/superset/docker-compose.yml run --rm \
  superset superset db upgrade

docker compose -f dashboard/superset/docker-compose.yml run --rm \
  superset superset fab create-admin

docker compose -f dashboard/superset/docker-compose.yml run --rm \
  superset superset init

docker compose -f dashboard/superset/docker-compose.yml up -d
```

A interface fica em [http://localhost:8088](http://localhost:8088). Conecte o banco usando:

```text
duckdb:////app/data/bi/financial_risk_bi.duckdb
```

## Pipeline local de machine learning

### 1. Sincronizar o mart de features

```bash
uv run --env-file .env python scripts/ml/sync_ml_datasets.py
```

O script baixa os Parquets para um snapshot local e grava `data/ml/manifest.json`.

### 2. Perfilar e avaliar baselines

```bash
uv run python scripts/ml/profile_ml_dataset.py
uv run python scripts/ml/evaluate_baselines.py
```

### 3. Preparar os splits temporais

```bash
uv run python scripts/ml/prepare_modeling_data.py
```

Arquivos gerados:

```text
data/ml/modeling/train_sample.parquet
data/ml/modeling/validation.parquet
data/ml/modeling/test.parquet
```

### 4. Versionar os datasets no S3

```bash
uv run --env-file .env python scripts/ml/publish_modeling_datasets.py
```

A versão é derivada dos hashes SHA-256 dos três arquivos. Repetir o comando com o mesmo conteúdo não reenvia os Parquets.

### 5. Iniciar o MLflow

Em um terminal separado:

```bash
uv run --env-file .env python scripts/ml/start_mlflow_server.py
```

A interface fica em [http://127.0.0.1:5000](http://127.0.0.1:5000).

- metadados e Model Registry: `data/ml/mlflow/tracking.db`;
- datasets versionados: `s3://<bucket>/financial-risk-platform/ml/datasets/`;
- artefatos do MLflow: `s3://<bucket>/financial-risk-platform/mlflow-artifacts/`.

### 6. Treinar os modelos

Regressão logística:

```bash
uv run --env-file .env python scripts/ml/train_logistic_regression.py
```

Random Forest:

```bash
uv run --env-file .env python scripts/ml/train_tree_models.py \
  --model random_forest
```

XGBoost:

```bash
uv run --env-file .env python scripts/ml/train_tree_models.py \
  --model xgboost
```

Cada execução registra parâmetros, métricas, datasets de entrada, importância ou coeficientes, assinatura de inferência e uma nova versão de `fraud-detection-classifier` no Model Registry.

### 7. Executar a EDA do grafo

```bash
uv run python scripts/ml/graph_eda.py
```

O relatório é salvo em `reports/ml/graph_eda/graph_overview.json`.

## Qualidade e validação

Verifique a sintaxe dos scripts de ML:

```bash
uv run python -m py_compile \
  scripts/ml/tree_models.py \
  scripts/ml/train_tree_models.py \
  scripts/ml/graph_eda.py
```

Execute apenas os testes dbt:

```bash
uv run --env-file .env dbt test \
  --profiles-dir .
```

Gere e visualize a documentação do dbt:

```bash
uv run --env-file .env dbt docs generate \
  --profiles-dir .

uv run --env-file .env dbt docs serve \
  --profiles-dir .
```

## Custos e segurança

- AWS Budgets cria alertas de gasto real e previsto;
- o workgroup do Athena centraliza resultados e controles;
- tabelas analíticas usam Parquet para reduzir dados escaneados;
- o bucket usa Block Public Access, criptografia SSE-S3 e versionamento;
- o treinamento ocorre localmente após uma única sincronização;
- uploads de datasets são idempotentes;
- credenciais e dados locais são ignorados pelo Git;
- nenhum recurso é criado com a conta root como prática recomendada.

O projeto usa boto3 para tornar as decisões visíveis e reproduzíveis. Em uma implantação corporativa, a infraestrutura deveria migrar para Terraform ou AWS CDK, credenciais estáticas deveriam ser substituídas por roles temporárias e o backend SQLite do MLflow deveria migrar para um banco compartilhado.

## Limitações

- PaySim é sintético e contém padrões mais determinísticos que fraudes reais;
- o treino usa amostragem de transações legítimas;
- as probabilidades não estão calibradas para a prevalência original;
- o threshold maximiza F1, mas uma operação real exigiria custos distintos para falsos positivos e falsos negativos;
- o MLflow possui backend local e não oferece alta disponibilidade;
- a topologia do PaySim é extremamente esparsa para GNNs tradicionais;
- ainda não existe serviço de inferência online nem monitoramento de drift.

## Próximos passos

- construir features históricas de grafo sem vazamento temporal;
- comparar XGBoost atual com XGBoost enriquecido por features de rede;
- calibrar probabilidades no conjunto de validação;
- selecionar threshold a partir de custos de negócio;
- adicionar testes automatizados dos scripts Python;
- criar pipeline CI para `dbt compile`, testes e lint;
- expor o modelo campeão por uma API de inferência;
- monitorar drift de dados, performance e volume de alertas.

## Documentação complementar

- [Pipeline dbt do projeto](docs/DBT_PIPELINE.md)
- [Guia geral de dbt](docs/DBT_GUIDE.md)
- [Infraestrutura AWS](scripts/aws/README.md)
- [Machine learning e MLflow](scripts/ml/README.md)
