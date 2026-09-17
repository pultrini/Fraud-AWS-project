{% macro safe_divide(
    numerator,
    denominator,
    multiplier=1.0
) -%}

    (
        cast({{ multiplier }} as double)
        * cast ({{ numerator }} as double)
        / nullif(
            cast({{ denominator }} as double),
            0.0
        )
    )

{%- endmacro %}
