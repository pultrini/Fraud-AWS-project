import json
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (
    OneHotEncoder,
    StandardScaler,
)

from mlflow_tracking import (
    configure_mlflow,
    log_common_run_metadata,
    log_dataset_input,
    log_sklearn_model,
    write_run_reference,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "ml"
    / "modeling"
)

ARTIFACT_DIRECTORY = (
    PROJECT_ROOT
    / "artifacts"
    / "models"
    / "logistic_regression"
)

CATEGORICAL_FEATURES = [
    "transaction_type",
    "destination_account_type",
]

BOOLEAN_FEATURES = [
    "origin_has_sufficient_balance",
    "destination_has_recorded_balance",
    "is_merchant_destination",
    "has_previous_transaction",
]

NUMERIC_FEATURES = [
    "simulation_hour",
    "day_of_simulation_week",
    "log_transaction_amount",
    "log_origin_balance_before",
    "log_destination_balance_before",
    "log_amount_to_origin_balance_ratio",
    "log_amount_to_destination_balance_ratio",
    "customer_transaction_number",
    "transaction_count_last_10",
    "transaction_count_24h",
    "transaction_count_7d",
]

SOURCE_COLUMNS = [
    "simulation_hour",
    "day_of_simulation_week",
    "transaction_type",
    "destination_account_type",
    "log_transaction_amount",
    "origin_balance_before",
    "destination_balance_before",
    "amount_to_origin_balance_ratio",
    "amount_to_destination_balance_ratio",
    "origin_has_sufficient_balance",
    "destination_has_recorded_balance",
    "is_merchant_destination",
    "has_previous_transaction",
    "customer_transaction_number",
    "transaction_count_last_10",
    "transaction_count_24h",
    "transaction_count_7d",
    "is_fraud",
]

def build_features(
        dataframe: pd.DataFrame
) -> pd.DataFrame:
    """Cria transformarções adequadas aos modelos lineares"""

    features = dataframe.copy()

    features["log_origin_balance_before"] = np.log1p(
        features['origin_balance_before'].clip(lower=0)
    )

    features["log_destination_balance_before"] = np.log1p(
        features['destination_balance_before'].clip(lower=0)
    )

    features["log_amount_to_origin_balance_ratio"] = np.log1p(
        features['amount_to_origin_balance_ratio'].clip(lower=0)
    )

    features["log_amount_to_destination_balance_ratio"] = np.log1p(
        features['amount_to_destination_balance_ratio'].clip(lower=0)
    )

    features = features.replace(
        [np.inf, -np.inf],
        np.nan
    )

    for column in BOOLEAN_FEATURES:
        features[column] = features[column].astype("float64")

    for column in NUMERIC_FEATURES:
        features[column] = features[column].astype("float64")

    selected_features = (
        CATEGORICAL_FEATURES + BOOLEAN_FEATURES + NUMERIC_FEATURES
    )

    return features[selected_features]

def load_dataset(
        filename: str
) -> tuple[pd.DataFrame, pd.Series]:
    """Carrega e separa features e alvo"""

    path = DATA_DIRECTORY / filename

    dataframe = pd.read_parquet(
        path,
        columns=SOURCE_COLUMNS
    )

    target = (
        dataframe.pop("is_fraud").astype("int8")
    )

    features = build_features(dataframe)

    return features, target


def create_pipeline() -> Pipeline:
    """Cria o pré-processamento e o modelo."""

    categorical_pipeline = Pipeline(
        steps=[
            (
                "missing_values",
                SimpleImputer(
                    strategy="most_frequent"
                ),
            ),
            (
                "one_hot",
                OneHotEncoder(
                    handle_unknown='ignore',
                    drop='first'
                ),
            ),
        ]
    )

    numeric_pipeline = Pipeline(
        steps=[
            (
                "missing_values",
                SimpleImputer(
                    strategy="median"
                ),
            ),
            (
                "scalar",
                StandardScaler(),
            ),
        ]
    )

    boolean_pipeline = Pipeline(
        steps=[
            (
                "missing_values",
                SimpleImputer(
                    strategy="most_frequent"
                ),
            ),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                categorical_pipeline,
                CATEGORICAL_FEATURES
            ),
            (
                "boolean",
                boolean_pipeline,
                BOOLEAN_FEATURES
            ),
            (
                "numeric",
                numeric_pipeline,
                NUMERIC_FEATURES
            ),
        ]
    )

    model = LogisticRegression(
        solver='lbfgs',
        C=1.0,
        class_weight='balanced',
        max_iter=1000,
        random_state=42
    )

    return Pipeline(
        steps=[
            (
                "preprocessor",
                preprocessor
            ),
            (
                "model",
                model
            )
        ]
    )


def select_threshold(
        target: pd.Series,
        probabilities: np.ndarray
) -> float:
    """Seleciona na validação o limiar com maior F1"""

    precision, recall, thresholds = (
        precision_recall_curve(
            target, probabilities
        )
    )

    denominator = precision[:-1] + recall[:-1]

    f1_values = np.divide(
        2 * precision[:-1] * recall[:-1], denominator, out=np.zeros_like(denominator), where=denominator != 0
    )

    best_index = int(np.argmax(f1_values))

    return float(thresholds[best_index])



def calculate_metrics(
    target: pd.Series,
    probabilities: np.ndarray,
    threshold: float,
) -> dict:
    """Calcula métricas de classificação."""

    predictions = (
        probabilities >= threshold
    ).astype("int8")

    true_negative, false_positive, \
        false_negative, true_positive = (
            confusion_matrix(
                target,
                predictions,
                labels=[0, 1],
            ).ravel()
        )

    return {
        "threshold": threshold,
        "true_positive": int(true_positive),
        "false_positive": int(false_positive),
        "false_negative": int(false_negative),
        "true_negative": int(true_negative),
        "generated_alerts": int(
            true_positive + false_positive
        ),
        "alert_rate_percent": float(
            100
            * predictions.mean()
        ),
        "precision_percent": float(
            100
            * precision_score(
                target,
                predictions,
                zero_division=0,
            )
        ),
        "recall_percent": float(
            100
            * recall_score(
                target,
                predictions,
                zero_division=0,
            )
        ),
        "f1_percent": float(
            100
            * f1_score(
                target,
                predictions,
                zero_division=0,
            )
        ),
        "average_precision": float(
            average_precision_score(
                target,
                probabilities,
            )
        ),
        "roc_auc": float(
            roc_auc_score(
                target,
                probabilities,
            )
        ),
    }

def save_coefficients(
    pipeline: Pipeline,
) -> None:
    """Salva os coeficientes para interpretação."""

    preprocessor = pipeline.named_steps[
        "preprocessor"
    ]

    model = pipeline.named_steps[
        "model"
    ]

    feature_names = (
        preprocessor
        .get_feature_names_out()
    )

    coefficients = pd.DataFrame(
        {
            "feature": feature_names,
            "coefficient": (
                model.coef_.ravel()
            ),
        }
    )

    coefficients[
        "absolute_coefficient"
    ] = coefficients[
        "coefficient"
    ].abs()

    coefficients = coefficients.sort_values(
        by="absolute_coefficient",
        ascending=False,
    )

    coefficients.to_csv(
        ARTIFACT_DIRECTORY
        / "coefficients.csv",
        index=False,
    )


def main() -> None:
    ARTIFACT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    configure_mlflow()

    print("Carregando treino...")

    train_features, train_target = load_dataset(
        "train_sample.parquet"
    )

    print("Carregando validação...")

    validation_features, validation_target = (
        load_dataset(
            "validation.parquet"
        )
    )

    with mlflow.start_run(run_name="logistic-regression"):
        manifest = log_common_run_metadata(
            model_name="logistic_regression",
            parameters={
                "solver": "lbfgs",
                "l1_ratio": 0.0,
                "C": 1.0,
                "class_weight": "balanced",
                "max_iter": 1000,
                "random_state": 42,
                "threshold_strategy": "best_validation_f1",
                "feature_count": len(train_features.columns),
            },
            metrics={},
            tags={"model_family": "linear"},
        )
        log_dataset_input(train_features, manifest, "training")
        log_dataset_input(validation_features, manifest, "validation")

        print("Criando e treinando o pipeline...")

        pipeline = create_pipeline()

        pipeline.fit(
            train_features,
            train_target,
        )

        print("Calculando probabilidades da validação...")

        validation_probabilities = (
            pipeline.predict_proba(
                validation_features
            )[:, 1]
        )

        selected_threshold = select_threshold(
            target=validation_target,
            probabilities=validation_probabilities,
        )

        validation_metrics = calculate_metrics(
            target=validation_target,
            probabilities=validation_probabilities,
            threshold=selected_threshold,
        )

        del validation_features
        del validation_probabilities

        print("Carregando teste...")

        test_features, test_target = load_dataset(
            "test.parquet"
        )
        log_dataset_input(test_features, manifest, "testing")

        test_probabilities = (
            pipeline.predict_proba(
                test_features
            )[:, 1]
        )

        test_metrics = calculate_metrics(
            target=test_target,
            probabilities=test_probabilities,
            threshold=selected_threshold,
        )

        metrics = {
            "model": "logistic_regression",
            "validation": validation_metrics,
            "test": test_metrics,
        }

        model_path = ARTIFACT_DIRECTORY / "model.joblib"
        metrics_path = ARTIFACT_DIRECTORY / "metrics.json"
        coefficients_path = ARTIFACT_DIRECTORY / "coefficients.csv"

        joblib.dump(pipeline, model_path)
        save_coefficients(pipeline)
        metrics_path.write_text(
            json.dumps(
                metrics,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        mlflow.log_metrics({
            f"{split}_{metric}": float(value)
            for split, split_metrics in metrics.items()
            if isinstance(split_metrics, dict)
            for metric, value in split_metrics.items()
            if isinstance(value, (int, float))
        })
        mlflow.log_artifact(str(metrics_path), artifact_path="evaluation")
        mlflow.log_artifact(str(coefficients_path), artifact_path="analysis")
        mlflow.log_artifact(str(model_path), artifact_path="local-export")
        log_sklearn_model(
            pipeline=pipeline,
            input_example=train_features.head(5),
        )
        write_run_reference(ARTIFACT_DIRECTORY / "mlflow_run.json")

    print("\nLimiar selecionado:")
    print(
        f"{selected_threshold:.6f}"
    )

    print("\nValidação:")
    print(
        json.dumps(
            validation_metrics,
            indent=2,
        )
    )

    print("\nTeste:")
    print(
        json.dumps(
            test_metrics,
            indent=2,
        )
    )

    print(
        f"\nArtefatos salvos em: "
        f"{ARTIFACT_DIRECTORY}"
    )
    print(f"Run MLflow: {mlflow.last_active_run().info.run_id}")


if __name__ == "__main__":
    main()
