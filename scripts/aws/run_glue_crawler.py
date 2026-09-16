import os
import time

import boto3
import dotenv

dotenv.load_dotenv()

CRAWLER_NAME = "financial-risk-paysim-raw-crawler"
DATABASE_NAME = "financial_risk_raw"



def main() -> None:
    region = os.environ["AWS_DEFAULT_REGION"]
    glue = boto3.Session(region_name=region).client("glue")

    crawler_info = glue.get_crawler(Name=CRAWLER_NAME)["Crawler"]
    initial_state = crawler_info["State"]

    print(f"Estado inicial do crawler '{CRAWLER_NAME}': {initial_state}")
    previous_crawl = crawler_info.get("LastCrawl")

    if initial_state == "READY" and previous_crawl:
        print(
        "O crawler já possui uma execução anterior. "
        "Nenhuma nova execução será iniciada."
        )
    elif initial_state=="READY":
        print("Iniciando o crawler...")
        glue.start_crawler(Name=CRAWLER_NAME)
        time.sleep(5)
    elif initial_state in ["RUNNING", "STOPPING"]:
        print("Crawler já está em execução/finalização. Entrando na etapa de monitoramento...")

    deadline = time.monotonic() + 15*60
    while time.monotonic() < deadline:
        crawler = glue.get_crawler(Name=CRAWLER_NAME)["Crawler"]
        state = crawler["State"]

        print(f"Estado do crawler: {state}")

        if state == "READY" and crawler.get("LastCrawl"):
            break

        time.sleep(15)
    else:
        raise TimeoutError("O crawler não terminou em 15 minutos.")

    last_crawl = crawler["LastCrawl"]
    status = last_crawl["Status"]

    if status != "SUCCEEDED":
        raise RuntimeError(
            f"Crawler terminou com status {status}: "
            f"{last_crawl.get('ErrorMessage', 'sem detalhes')}"
        )

    print(f"\nCrawler concluído com sucesso (Status: {status}).\n")

    print(f"=== Tabelas no Database '{DATABASE_NAME}' ===")
    response = glue.get_tables(DatabaseName=DATABASE_NAME)

    for table in response.get("TableList", []):
        storage = table.get("StorageDescriptor", {})

        print(f"Tabela: {table['Name']}")
        print(f"Localização: {storage.get('Location', 'N/A')}")
        print(f"Classificação: {table.get('Parameters', {}).get('classification', 'N/A')}")
        print("Colunas:")

        for column in storage.get("Columns", []):
            print(f"  {column['Name']}: {column['Type']}")


if __name__ == "__main__":
    main()