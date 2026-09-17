{% macro fraud_rate(
    fraud_count_column,
    transaction_count_column
) -%}

    {{
        safe_divide(
            fraud_count_column,
            transaction_count_column,
            100.0
        )
    }}

{%- endmacro %}