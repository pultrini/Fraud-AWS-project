# Guia geral de dbt

Este guia apresenta os conceitos centrais do dbt e um fluxo prático de uso. Os exemplos de terminal seguem este repositório, que usa `uv`, dbt Core e Athena, mas os conceitos valem para outros adaptadores.

## 1. O que é dbt

dbt é uma ferramenta de transformação de dados. Ela permite escrever transformações como consultas `select`, organizar dependências, materializar resultados no mecanismo de dados, aplicar testes e gerar documentação e linhagem.

Em uma arquitetura ELT:

1. uma ferramenta extrai os dados da origem;
2. os dados são carregados no warehouse ou data lake;
3. o dbt transforma os dados dentro desse mecanismo.

dbt cuida principalmente do terceiro passo. Ele não substitui, por si só, ingestão, armazenamento, catálogo, dashboard ou treinamento de ML.

```text
Origem -> extração/carga -> dados brutos -> dbt -> dados confiáveis -> BI/ML
```

## 2. dbt Core, adaptador e mecanismo de dados

Três componentes cooperam:

- **dbt Core** interpreta o projeto, Jinja, dependências, seleções, testes e comandos;
- **adaptador** traduz particularidades da plataforma e abre a conexão, como `dbt-athena`;
- **mecanismo de dados** executa o SQL, como Athena, Postgres, BigQuery, Snowflake ou Databricks.

No projeto atual, as versões estão fixadas em `pyproject.toml`:

```toml
"dbt-athena==1.11.0",
"dbt-core>=1.11,<1.12",
```

Fixar faixas compatíveis melhora a reprodutibilidade. Antes de atualizar, leia as notas de versão do Core e do adaptador.

## 3. Anatomia de um projeto

Uma estrutura comum é:

```text
dbt_project.yml        # configuração do projeto
profiles.yml           # conexão e targets
models/                # modelos SQL/Python e propriedades YAML
├── staging/
├── intermediate/
└── marts/
seeds/                 # pequenos CSVs versionados
snapshots/             # histórico de registros mutáveis
macros/                # código Jinja reutilizável
tests/                 # testes singulares SQL
analyses/              # consultas compiladas, não materializadas
selectors.yml          # seleções nomeadas
target/                # SQL compilado e artefatos gerados
logs/                  # logs locais
```

Nem todo projeto precisa usar todos os diretórios.

## 4. `dbt_project.yml` e `profiles.yml`

`dbt_project.yml` descreve o projeto e configura seus recursos:

```yaml
name: meu_projeto
version: "1.0.0"
config-version: 2
profile: meu_profile

model-paths: ["models"]

models:
  meu_projeto:
    staging:
      +materialized: view
    marts:
      +materialized: table
```

O sinal `+` distingue configurações aplicadas aos recursos de chaves que representam pastas ou modelos.

`profiles.yml` descreve onde executar:

```yaml
meu_profile:
  target: dev
  outputs:
    dev:
      type: athena
      database: awsdatacatalog
      schema: meu_schema_dev
      region_name: "{{ env_var('AWS_DEFAULT_REGION') }}"
      threads: 4
```

Um profile pode ter targets como `dev` e `prod`. O mesmo código é compilado para ambientes diferentes sem inserir credenciais ou schemas no SQL.

Boas práticas:

- nunca versionar segredos;
- ler credenciais de variáveis de ambiente ou do mecanismo padrão do provedor;
- usar schemas separados para desenvolvimento e produção;
- testar a conexão com `dbt debug`.

Neste repositório, o profile está na raiz, então todos os comandos incluem `--profiles-dir .`.

## 5. Modelos

Um modelo SQL é normalmente um arquivo que termina em um único `select`:

```sql
with orders as (
    select *
    from {{ ref('stg_orders') }}
),

aggregated as (
    select
        customer_id,
        count(*) as order_count,
        sum(order_amount) as order_amount_total
    from orders
    group by customer_id
)

select *
from aggregated
```

O nome do arquivo, como `customer_orders.sql`, torna-se por padrão o nome do modelo e da relação criada.

CTEs com nomes claros ajudam a separar passos lógicos. Evite embutir nomes físicos de tabelas dependentes; use `source()` e `ref()`.

## 6. Sources e `source()`

Uma source representa dados que já existem antes do dbt, normalmente carregados por ingestão:

```yaml
version: 2

sources:
  - name: app_raw
    database: catalog
    schema: raw
    tables:
      - name: orders
```

O modelo consulta a source assim:

```sql
select *
from {{ source('app_raw', 'orders') }}
```

Isso permite que o dbt:

- resolva o nome físico;
- registre a origem no DAG;
- documente e teste a tabela externa;
- selecione modelos a partir da source.

Exemplo de seleção:

```bash
dbt test --select source:app_raw.orders
dbt run --select source:app_raw.orders+
```

## 7. `ref()` e o DAG

`ref()` aponta para outro modelo, seed ou snapshot:

```sql
select *
from {{ ref('stg_orders') }}
```

Durante a compilação, dbt substitui a chamada pelo nome físico adequado. Ao mesmo tempo, cria uma aresta de dependência:

```text
stg_orders -> customer_orders
```

Com várias referências, forma-se um DAG, um grafo dirigido sem ciclos. dbt usa esse grafo para construir recursos na ordem correta. Um modelo não pode depender direta ou indiretamente de si mesmo.

## 8. Jinja: compilação antes da execução

Blocos `{{ ... }}` imprimem uma expressão no SQL; blocos `{% ... %}` controlam a geração:

```sql
select
    {{ var('tax_rate', 0.2) }} * amount as tax_amount
from {{ ref('orders') }}

{% if target.name == 'dev' %}
limit 1000
{% endif %}
```

O banco não entende Jinja. O dbt primeiro compila o template em SQL puro e depois envia esse SQL ao mecanismo.

Use `dbt compile` para inspecionar o resultado em `target/compiled/` quando um erro parece estar na interação entre Jinja e SQL.

## 9. Materializações

A materialização define como o resultado do `select` será representado.

### View

```sql
{{ config(materialized='view') }}
```

- armazena a consulta, não uma cópia dos dados;
- é rápida para criar;
- sempre reflete os dados a montante;
- transfere o custo de transformação para cada consulta.

É adequada para staging simples e relações leves.

### Table

```sql
{{ config(materialized='table') }}
```

- persiste o resultado;
- acelera leituras repetidas e cálculos caros;
- exige reconstrução para refletir alterações;
- consome armazenamento.

É adequada para marts e transformações reutilizadas muitas vezes.

### Incremental

```sql
{{ config(materialized='incremental') }}

select *
from {{ ref('events') }}

{% if is_incremental() %}
where event_time >= (
    select max(event_time) from {{ this }}
)
{% endif %}
```

Na criação inicial, todas as linhas são processadas. Depois, `is_incremental()` é verdadeiro quando a relação já existe, não foi solicitado `--full-refresh` e a materialização continua incremental.

O desenvolvedor precisa definir:

- como localizar registros novos ou alterados;
- como evitar duplicatas;
- como tratar registros atrasados;
- como reagir a mudanças de schema.

Estratégias como `append`, `merge` e `insert_overwrite` dependem do adaptador e do tipo de tabela. Consulte a documentação do adaptador antes de escolher.

Para reconstruir tudo:

```bash
dbt run --full-refresh --select meu_modelo
```

### Ephemeral

```sql
{{ config(materialized='ephemeral') }}
```

Não cria uma relação no banco. O dbt injeta o SQL como CTE nos modelos dependentes. É útil para lógica pequena e usada por poucos consumidores, mas pode produzir SQL compilado grande e dificultar depuração.

## 10. Propriedades, documentação e contratos

Arquivos `.yml` descrevem modelos e colunas:

```yaml
version: 2

models:
  - name: customer_orders
    description: "Uma linha por cliente com suas métricas de pedidos."
    columns:
      - name: customer_id
        description: "Identificador único do cliente."
        data_tests:
          - not_null
          - unique
```

A descrição deve explicar significado e granularidade, não apenas repetir o nome da coluna.

Essas propriedades alimentam o catálogo gerado por `dbt docs generate` e tornam o modelo mais compreensível para consumidores.

## 11. Data tests

Um data test é uma consulta que procura registros que violam uma expectativa. O teste passa se a consulta retornar zero linhas.

### Testes genéricos

São parametrizados e declarados em YAML:

```yaml
columns:
  - name: status
    data_tests:
      - not_null
      - accepted_values:
          arguments:
            values: ['OPEN', 'CLOSED']

  - name: customer_id
    data_tests:
      - relationships:
          arguments:
            to: ref('dim_customer')
            field: customer_id
```

Os quatro genéricos mais comuns são:

- `not_null`;
- `unique`;
- `accepted_values`;
- `relationships`.

### Testes singulares

São arquivos SQL em `tests/`:

```sql
select *
from {{ ref('payments') }}
where payment_amount < 0
```

Eles expressam regras específicas do negócio ou invariantes entre modelos.

Não escreva um teste que retorna a linha válida. Escreva a consulta que retorna apenas falhas.

## 12. Seeds

Seeds são pequenos CSVs versionados carregados pelo dbt:

```bash
dbt seed
```

Depois podem ser referenciados normalmente:

```sql
select * from {{ ref('country_codes') }}
```

Use seeds para dados estáticos e pequenos, como mapeamentos e códigos de domínio. Não os use para fatos grandes ou dados atualizados continuamente.

## 13. Snapshots

Snapshots registram como linhas mutáveis mudam ao longo do tempo. São úteis quando a fonte mantém apenas o estado atual, mas a análise precisa do histórico, como mudanças de endereço ou status.

As estratégias usuais são:

- `timestamp`: detecta mudanças por uma coluna de atualização;
- `check`: compara um conjunto de colunas.

Snapshot não é necessário quando a fonte já é um log imutável de eventos, como o PaySim deste projeto.

## 14. Macros

Macros são funções Jinja que geram SQL:

```sql
{% macro cents_to_currency(column_name) %}
    cast({{ column_name }} as decimal(18, 2)) / 100
{% endmacro %}
```

Uso:

```sql
select {{ cents_to_currency('amount_cents') }} as amount
from {{ ref('payments') }}
```

Macros são apropriadas para padrões repetidos, diferenças entre bancos e regras de SQL centralizadas. Não transforme toda consulta em abstração: SQL direto costuma ser mais fácil de ler quando a lógica aparece apenas uma vez.

## 15. Variáveis e variáveis de ambiente

Uma variável de projeto pode ter valor padrão em `dbt_project.yml`:

```yaml
vars:
  history_start_date: '2025-01-01'
```

Uso:

```sql
where event_date >= date '{{ var("history_start_date") }}'
```

Ela também pode ser sobrescrita na execução:

```bash
dbt run --vars '{history_start_date: 2026-01-01}'
```

Variáveis de ambiente são lidas com `env_var()`:

```yaml
schema: "{{ env_var('DBT_SCHEMA') }}"
```

Use `env_var()` para configuração externa e segredos. Use `var()` para parâmetros lógicos do projeto. Segredos nunca devem aparecer no SQL compilado, nos logs ou no controle de versão.

## 16. Seleção de nós

Evitar executar o projeto inteiro durante cada mudança economiza tempo e custo.

| Sintaxe | Significado |
|---|---|
| `modelo` | Somente o modelo |
| `+modelo` | Modelo e todos os ancestrais |
| `modelo+` | Modelo e todos os descendentes |
| `+modelo+` | Ancestrais, modelo e descendentes |
| `tag:fraud` | Recursos com a tag |
| `path:models/marts` | Recursos no caminho |
| `source:nome.tabela+` | Source e descendentes |

`dbt ls` mostra a seleção sem construir relações:

```bash
dbt ls --select +mart_fraud_daily
dbt ls --select tag:ml
```

Seletores nomeados ficam em `selectors.yml`:

```yaml
selectors:
  - name: ml_pipeline
    definition:
      method: tag
      value: ml
      parents: true
```

Uso:

```bash
dbt build --selector ml_pipeline
```

## 17. Comandos essenciais

Nos exemplos deste repositório, o prefixo completo é:

```bash
uv run --env-file .env dbt <comando> --profiles-dir .
```

### Diagnóstico e inspeção

```bash
dbt debug                       # valida projeto, profile e conexão
dbt parse                       # interpreta o projeto sem executar modelos
dbt ls                          # lista recursos ou uma seleção
dbt compile --select modelo     # gera SQL puro em target/compiled
dbt show --select modelo        # mostra uma amostra do resultado
```

### Construção

```bash
dbt seed                        # carrega CSVs de seeds
dbt run                         # executa modelos
dbt test                        # executa data tests
dbt build                       # executa recursos selecionados e seus testes em ordem do DAG
```

`dbt build` é geralmente a melhor validação integrada. Se um teste de um recurso falhar, nós dependentes podem ser ignorados para impedir a publicação de dados construídos sobre uma entrada inválida.

### Documentação e limpeza

```bash
dbt docs generate               # gera catálogo, manifesto e site estático
dbt docs serve                  # abre o site local de documentação
dbt clean                       # remove caminhos declarados em clean-targets
```

`dbt docs serve` mantém um processo local ativo; interrompa com `Ctrl+C`.

## 18. Diferença entre comandos que parecem semelhantes

### `compile`, `run`, `test` e `build`

- `compile` valida Jinja e produz SQL, mas não materializa o modelo;
- `run` materializa apenas modelos;
- `test` consulta os testes existentes contra relações já construídas;
- `build` inclui modelos, testes, seeds e snapshots selecionados na ordem do grafo.

Uma compilação bem-sucedida prova que o template virou SQL, mas não garante que o mecanismo aceitará esse SQL ou que os dados passarão nos testes.

### `show` e `run`

- `show` executa uma consulta de prévia e exibe linhas;
- `run` cria ou substitui a relação conforme sua materialização.

### `ref()` e `source()`

- `source()` aponta para uma tabela externa ao ciclo de construção do projeto;
- `ref()` aponta para um recurso administrado pelo dbt.

## 19. Fluxo de desenvolvimento recomendado

Para criar ou alterar um modelo:

1. defina a granularidade e o consumidor;
2. escreva o `select` usando `source()` e `ref()`;
3. adicione descrição do modelo e das colunas importantes;
4. declare testes de chave, preenchimento, domínio e relacionamento;
5. adicione testes singulares para regras de negócio;
6. compile o modelo;
7. execute uma prévia com `show`, quando apropriado;
8. construa apenas o modelo e seus testes;
9. execute a seleção de integração relevante;
10. revise SQL compilado, custo e plano de materialização.

Exemplo:

```bash
uv run --env-file .env dbt compile \
  --profiles-dir . \
  --select novo_modelo

uv run --env-file .env dbt build \
  --profiles-dir . \
  --select +novo_modelo
```

Antes de usar `+novo_modelo` em uma plataforma cobrada por leitura, confira o conjunto com `dbt ls`.

## 20. Desenvolvimento, CI e produção

Um fluxo maduro costuma separar:

- desenvolvimento local em schema próprio;
- revisão de código e validação automatizada;
- execução de produção com credenciais e target dedicados;
- monitoramento de falhas, duração e freshness;
- artefatos de execução preservados para auditoria.

Uma validação de CI pode começar com:

```bash
dbt deps
dbt parse
dbt build --select state:modified+
```

Seleção por `state` requer artefatos de uma execução anterior e configuração apropriada de `--state`. Não copie esse exemplo para CI sem definir onde o `manifest.json` anterior será armazenado.

## 21. Custo e desempenho

dbt não elimina o modelo de cobrança da plataforma. Em Athena, uma consulta pode custar pela quantidade de bytes examinados.

Práticas importantes:

- prefira Parquet/ORC a CSV para tabelas transformadas;
- selecione apenas colunas necessárias;
- filtre colunas particionadas;
- evite reconstruir todo o DAG durante uma mudança local;
- materialize cálculos caros e reutilizados;
- use incremental apenas com uma estratégia correta de atualização;
- avalie o custo dos testes que fazem scans completos;
- use `dbt ls` antes de seleções com operadores de grafo.

Materializar tudo como tabela não é automaticamente mais barato. O equilíbrio depende da frequência de atualização, quantidade de consumidores e custo de recomputação.

## 22. Diagnóstico de erros comuns

### “Selection criterion does not match any enabled nodes”

O nome selecionado não corresponde a um recurso habilitado. Confira:

```bash
dbt ls
dbt ls --resource-type test
```

Testes singulares recebem por padrão o nome do arquivo sem `.sql`.

### “depends on a node ... which was not found”

Uma chamada `ref('nome')` aponta para um nome inexistente ou digitado incorretamente. `ref()` usa o nome do recurso, normalmente o nome do arquivo, não o nome de uma coluna.

### “COLUMN_NOT_FOUND”

O YAML ou um modelo dependente espera uma coluna ausente no SQL materializado. Compare:

- o `select` final do modelo;
- o arquivo `.yml`;
- `target/compiled/`;
- o schema físico existente.

Se a relação antiga estiver desatualizada, reconstrua o modelo depois de corrigir o SQL.

### Erro de sintaxe aponta para uma linha estranha

Inspecione o SQL compilado. Uma macro pode gerar um operador inválido e o parser pode só perceber o problema na expressão seguinte:

```bash
dbt compile --select modelo
```

### Teste falhou versus teste deu erro

- `FAIL` significa que a consulta do teste rodou e encontrou linhas inválidas;
- `ERROR` significa que o teste não conseguiu executar, por exemplo por coluna inexistente, permissão ou SQL inválido.

### Configuração não utilizada

O aviso `unused configuration paths` indica que uma chave de configuração não corresponde a nenhum recurso atual. Pode ser apenas uma pasta planejada, mas nomes e indentação devem ser revisados.

## 23. Princípios práticos

- Comece pela granularidade, não pelo SQL.
- Use staging como fronteira limpa para cada source.
- Dê nomes que expressem a finalidade do modelo.
- Centralize lógica compartilhada, mas não esconda SQL simples atrás de macros desnecessárias.
- Teste chaves e regras de negócio.
- Trate testes como código de produção.
- Confira o SQL compilado quando usar Jinja.
- Considere custo e atualização ao escolher materialização.
- Não use informação futura em features de ML.
- Gere documentação como parte da entrega, não como tarefa posterior.

## 24. Referências oficiais

- [Modelos dbt](https://docs.getdbt.com/docs/build/models)
- [Sources](https://docs.getdbt.com/docs/build/sources)
- [Função `ref`](https://docs.getdbt.com/reference/dbt-jinja-functions/ref)
- [Data tests](https://docs.getdbt.com/docs/build/data-tests)
- [Modelos incrementais](https://docs.getdbt.com/docs/build/incremental-models)
- [Seletores YAML](https://docs.getdbt.com/reference/node-selection/yaml-selectors)
- [Comando `dbt build`](https://docs.getdbt.com/reference/commands/build)
- [Comandos `dbt docs`](https://docs.getdbt.com/reference/commands/cmd-docs)

