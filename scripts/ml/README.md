# Machine learning e MLflow

Esta camada treina os modelos localmente para evitar consultas repetidas no Athena. Os dados preparados e os artefatos de cada experimento são armazenados no S3 para garantir reprodutibilidade.

## Arquitetura

- `data/ml/modeling/`: cópia local dos splits de treino, validação e teste.
- `s3://<bucket>/financial-risk-platform/ml/datasets/`: versões imutáveis dos datasets.
- `data/ml/mlflow/tracking.db`: metadados e Model Registry local do MLflow.
- `s3://<bucket>/financial-risk-platform/mlflow-artifacts/`: modelos, métricas e demais artefatos dos runs.
- `artifacts/models/`: exportações locais convenientes, ignoradas pelo Git.

Os splits recebem uma versão derivada do SHA-256 dos três arquivos. Se o conteúdo não mudar, executar a publicação novamente não duplica os Parquets no S3.

## Configuração

Copie as variáveis relevantes de `.env.example` para `.env`. As credenciais AWS nunca devem ser commitadas. O bucket precisa existir e a identidade AWS precisa ter permissão de leitura e escrita nos prefixos usados.

## Fluxo completo

### 1. Preparar os splits locais

```bash
uv run --env-file .env python scripts/ml/prepare_modeling_data.py
```

### 2. Publicar uma versão dos datasets

```bash
uv run --env-file .env python scripts/ml/publish_modeling_datasets.py
```

O comando calcula hashes, coleta esquema e contagens, envia somente arquivos ausentes ou alterados e cria `data/ml/modeling/dataset_manifest.json`. Cada treinamento exige esse manifesto, ligando o run à versão exata dos dados.

### 3. Iniciar o MLflow

Em um terminal separado:

```bash
uv run --env-file .env python scripts/ml/start_mlflow_server.py
```

A interface fica em `http://127.0.0.1:5000`. O servidor mantém o catálogo local em SQLite e atua como proxy para salvar os artefatos no S3; por isso as credenciais AWS ficam apenas no processo do servidor.

### 4. Treinar e registrar um modelo

```bash
uv run --env-file .env python scripts/ml/train_logistic_regression.py
```

O run registra parâmetros, métricas de validação e teste, as três entradas de dados, coeficientes, exportação local e o pipeline completo. O pipeline também ganha uma nova versão no Model Registry `fraud-detection-classifier`.

## Reutilizar em novos modelos

Um novo script de treinamento deve:

1. chamar `configure_mlflow()`;
2. abrir `with mlflow.start_run(run_name="...")`;
3. chamar `log_common_run_metadata(...)` e guardar o manifesto retornado;
4. registrar cada split com `log_dataset_input(...)`;
5. registrar métricas e artefatos;
6. chamar `log_sklearn_model(...)` para pipelines scikit-learn;
7. salvar a referência com `write_run_reference(...)`.

Todos os modelos compartilham a mesma versão de dados e o mesmo nome lógico no Registry. Cada treinamento cria um run e uma versão novos, permitindo comparar algoritmos sem sobrescrever o histórico.

## Custos e operação

O treinamento e a leitura dos Parquets acontecem localmente. O S3 gera apenas custos baixos de armazenamento e requisições durante publicação e logging. O SQLite é adequado para este projeto local; em uma implantação compartilhada, o backend do MLflow deve migrar para PostgreSQL ou outro banco suportado.
