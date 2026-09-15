import duckdb
from pathlib import Path

RAW_FILE_PATH = Path("data/raw/PS_20174392719_1491204439457_log.csv")

def main() -> None:
    if not RAW_FILE_PATH.exists():
        raise FileNotFoundError(f"Arquivo não encontrado em: {RAW_FILE_PATH.resolve()}")

    connection = duckdb.connect()
    query= """
            SELECT
                COUNT(*) AS total_transacoes,
                MIN(step) AS primeiro_step,
                MAX(step) AS ultimo_step,
                COUNT(DISTINCT type) as qtd_tipos_distintos,
                SUM(
                    CASE
                        WHEN isFraud = 1 THEN 1
                        ELSE 0
                    END
                ) AS fraud_transactions,
                SUM(CAST(amount AS DECIMAL(18, 2))) AS valor_total,
                ROUND(AVG(amount), 2) AS valor_medio,
                ROUND(AVG(isFraud * 100), 4) AS pct_fraude
            FROM read_csv_auto(?)
    """

    connection.sql(query, params=[str(RAW_FILE_PATH)]).show()
    connection.close
    
if __name__ == "__main__":
    main()