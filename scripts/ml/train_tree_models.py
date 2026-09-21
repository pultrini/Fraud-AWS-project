import argparse
import json
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)


from mlflow_tracking import (
    configure_mlflow,
    flatten_metrics,
    log_common_run_metadata,
    log_dataset_input,
    log_sklearn_model,
    write_run_reference,
)

from tree_models import (
    ModelName,
    create_tree_model
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "ml"
    / "modeling"
)

ARTIFACT_ROOT = (
    PROJECT_ROOT
    / "artifacts"
    / "models"
)


CATEGORICAL_FEATURES = [
    "transaction_type",
    "destination_account_type",
]

BOOLEAN_FEATURES = [
    # "origin_has_sufficient_balance",
    "destination_has_recorded_balance",
    "is_merchant_destination",
    "has_previous_transaction",
]

NUMERIC_FEATURES = [
    "simulation_hour",
    "day_of_simulation_week",
    "log_transaction_amount",
    "origin_balance_before",
    "destination_balance_before",
    # "amount_to_origin_balance_ratio",
    "amount_to_destination_balance_ratio",
    "customer_transaction_number",
    "transaction_count_last_10",
    "transaction_count_24h",
    "transaction_count_7d",
]

SOURCE_COLUMNS = (
    CATEGORICAL_FEATURES
    + BOOLEAN_FEATURES
    + NUMERIC_FEATURES
    + ["is_fraud"]
)

def build_features(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Normaliza os tipos usados pelos modelos de árvore."""

    features = dataframe.copy()

    features = features.replace(
        [np.inf, -np.inf],
        np.nan,
    )

    for column in CATEGORICAL_FEATURES:
        features[column] = (
            features[column]
            .astype("string")
            .fillna("__MISSING__")
        )

    for column in BOOLEAN_FEATURES:
        features[column] = (
            features[column]
            .astype("float32")
        )

    for column in NUMERIC_FEATURES:
        features[column] = (
            features[column]
            .astype("float32")
        )

    selected_features = (
        CATEGORICAL_FEATURES
        + BOOLEAN_FEATURES
        + NUMERIC_FEATURES
    )

    return features[selected_features]

def load_dataset(
    filename: str,
) -> tuple[pd.DataFrame, pd.Series]:
    """Carrega um split e separa features e alvo."""

    dataset_path = DATA_DIRECTORY / filename

    if not dataset_path.is_file():
        raise FileNotFoundError(
            f"Dataset não encontrado: {dataset_path}"
        )

    dataframe = pd.read_parquet(
        dataset_path,
        columns=SOURCE_COLUMNS,
    )

    target = (
        dataframe
        .pop("is_fraud")
        .astype("int8")
    )

    features = build_features(dataframe)

    return features, target

def create_preprocessor() -> ColumnTransformer:
    """Cria o pré-processamento compartilhado pelos dois modelos."""

    categorical_pipeline = Pipeline(
        steps=[
            (
                "missing_values",
                SimpleImputer(
                    strategy="most_frequent",
                ),
            ),
            (
                "one_hot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    dtype=np.float32,
                ),
            ),
        ]
    )

    numeric_pipeline = Pipeline(
        steps=[
            (
                "missing_values",
                SimpleImputer(
                    strategy="median",
                ),
            ),
        ]
    )

    boolean_pipeline = Pipeline(
        steps=[
            (
                "missing_values",
                SimpleImputer(
                    strategy="most_frequent",
                ),
            ),
        ]
    )

    return ColumnTransformer(
        transformers=[
            (
                "categorical",
                categorical_pipeline,
                CATEGORICAL_FEATURES,
            ),
            (
                "boolean",
                boolean_pipeline,
                BOOLEAN_FEATURES,
            ),
            (
                "numeric",
                numeric_pipeline,
                NUMERIC_FEATURES,
            ),
        ],
        sparse_threshold=1.0,
    )

def calculate_scale_pos_weight(
        target: pd.Series
) -> float:
    """Calcula o peso da fraude usando somente o treino."""

    legitimate_count = int((target == 0).sum())
    fraud_count = int((target == 1).sum())

    if fraud_count == 0:
        raise ValueError(
            "O conjunto de treino não contém fraudes."
        )

    return legitimate_count / fraud_count



def parse_arguments() -> argparse.Namespace:
    """Lê os argumentos informados via termianl"""

    parser = argparse.ArgumentParser(
        description=(
            "Treina Random Forest ou XGBoost para detectar fraude"
        )
    )
    parser.add_argument(
        "--model",
        required=True,
        choices=[
            "random_forest",
            "xgboost",
        ],
        help="Modelo que será treinado.",
    )

    parser.add_argument(
        "--n-jobs",
        type=int,
        default=-1,
        help=(
            "Quantidade de núcleos utilizados. "
            "O valor -1 utiliza todos os disponíveis."
        ),
    )

    return parser.parse_args()


def fit_tree_model(
    *,
    model_name: ModelName,
    train_features: pd.DataFrame,
    train_target: pd.Series,
    validation_features: pd.DataFrame,
    validation_target: pd.Series,
    n_jobs: int,
) -> tuple[
    Pipeline,
    np.ndarray,
    dict[str, str | int | float],
]:
    """Prepara os dados e treina o modelo selecionado."""

    print("Ajustando o pré-processador...")

    preprocessor = create_preprocessor()

    transformed_train = (
        preprocessor.fit_transform(
            train_features,
        )
    )

    transformed_validation = (
        preprocessor.transform(
            validation_features,
        )
    )

    scale_pos_weight = (
        calculate_scale_pos_weight(
            train_target
        )
    )

    print(
        "Proporção legítimas/fraudes no treino: "
        f"{scale_pos_weight:.2f}"
    )

    model = create_tree_model(
        model_name=model_name,
        scale_pos_weight=(
            scale_pos_weight
            if model_name == "xgboost"
            else None
        ),
        n_jobs=n_jobs,
    )

    print(
        f"Treinando modelo: {model_name}"
    )

    if model_name == "xgboost":
        model.fit(
            transformed_train,
            train_target,
            eval_set=[
                (
                    transformed_validation,
                    validation_target,
                )
            ],
            verbose=False,
        )
    else:
        model.fit(
            transformed_train,
            train_target,
        )

    validation_probabilities = (
        model.predict_proba(
            transformed_validation,
        )[:, 1]
    )

    pipeline = Pipeline(
        steps=[
            (
                "preprocessor",
                preprocessor,
            ),
            (
                "model",
                model,
            ),
        ]
    )


    training_metadata: dict[
        str,
        str | int | float,
    ] = {
        "model_name": model_name,
        "scale_pos_weight": scale_pos_weight,
        "train_row_count": len(
            train_features
        ),
        "validation_row_count": len(
            validation_features
        ),
        "feature_count_before_encoding": len(
            train_features.columns
        ),
    }

    if model_name == "random_forest":
        training_metadata[
            "oob_score"
        ] = float(model.oob_score_)

    if model_name == "xgboost":
        training_metadata[
            "best_iteration"
        ] = int(model.best_iteration)

        training_metadata[
            "best_validation_aucpr"
        ] = float(model.best_score)

    return (
        pipeline,
        validation_probabilities,
        training_metadata,
    )


def select_threshold(
    target: pd.Series,
    probabilities: np.ndarray,
) -> float:
    """Seleciona na validação o threshold com maior F1."""

    precision, recall, thresholds = (
        precision_recall_curve(
            target,
            probabilities,
        )
    )

    denominator = (
        precision[:-1] + recall[:-1]
    )

    f1_values = np.divide(
        2 * precision[:-1] * recall[:-1],
        denominator,
        out=np.zeros_like(denominator),
        where=denominator != 0,
    )

    best_index = int(
        np.argmax(f1_values)
    )

    return float(
        thresholds[best_index]
    )


def calculate_metrics(
    *,
    target: pd.Series,
    probabilities: np.ndarray,
    threshold: float,
) -> dict[str, float | int]:
    """Calcula métricas usando o threshold selecionado."""

    predictions = (
        probabilities >= threshold
    ).astype("int8")

    (
        true_negative,
        false_positive,
        false_negative,
        true_positive,
    ) = confusion_matrix(
        target,
        predictions,
        labels=[0, 1],
    ).ravel()

    return {
        "threshold": float(threshold),
        "true_positive": int(true_positive),
        "false_positive": int(false_positive),
        "false_negative": int(false_negative),
        "true_negative": int(true_negative),
        "generated_alerts": int(
            true_positive + false_positive
        ),
        "alert_rate_percent": float(
            100 * predictions.mean()
        ),
        "precision_percent": float(
            100 * precision_score(
                target,
                predictions,
                zero_division=0,
            )
        ),
        "recall_percent": float(
            100 * recall_score(
                target,
                predictions,
                zero_division=0,
            )
        ),
        "f1_percent": float(
            100 * f1_score(
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


def save_feature_importances(
    *,
    pipeline: Pipeline,
    destination: Path,
) -> None:
    """Salva a importância calculada pelo modelo."""

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

    feature_importances = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": (
                model.feature_importances_
            ),
        }
    )

    feature_importances = (
        feature_importances
        .sort_values(
            by="importance",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    feature_importances.to_csv(
        destination,
        index=False,
    )


def get_loggable_model_parameters(
    pipeline: Pipeline,
) -> dict[str, str | int | float | bool]:
    """Seleciona parâmetros simples para registrar no MLflow."""

    model = pipeline.named_steps[
        "model"
    ]

    parameters = {}

    for name, value in model.get_params().items():
        if value is None:
            continue

        if isinstance(
            value,
            (str, int, float, bool),
        ):
            parameters[name] = value

    return parameters


def main() -> None:
    arguments = parse_arguments()

    model_name: ModelName = (
        arguments.model
    )

    artifact_directory = (
        ARTIFACT_ROOT / model_name
    )

    artifact_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    configure_mlflow()

    print("Carregando treino...")

    train_features, train_target = (
        load_dataset(
            "train_sample.parquet"
        )
    )

    print("Carregando validação...")

    (
        validation_features,
        validation_target,
    ) = load_dataset(
        "validation.parquet"
    )

    with mlflow.start_run(
        run_name=model_name.replace(
            "_",
            "-",
        )
    ):
        (
            pipeline,
            validation_probabilities,
            training_metadata,
        ) = fit_tree_model(
            model_name=model_name,
            train_features=train_features,
            train_target=train_target,
            validation_features=(
                validation_features
            ),
            validation_target=(
                validation_target
            ),
            n_jobs=arguments.n_jobs,
        )

        print(
            "Selecionando threshold "
            "na validação..."
        )

        selected_threshold = (
            select_threshold(
                target=validation_target,
                probabilities=(
                    validation_probabilities
                ),
            )
        )

        validation_metrics = (
            calculate_metrics(
                target=validation_target,
                probabilities=(
                    validation_probabilities
                ),
                threshold=selected_threshold,
            )
        )

        print("Carregando teste...")

        test_features, test_target = (
            load_dataset(
                "test.parquet"
            )
        )

        print(
            "Calculando probabilidades "
            "do teste..."
        )

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

        training_metrics = {
            key: value
            for key, value
            in training_metadata.items()
            if (
                key
                in {
                    "oob_score",
                    "best_iteration",
                    "best_validation_aucpr",
                }
                and isinstance(
                    value,
                    (int, float),
                )
            )
        }

        metrics = {
            "training": training_metrics,
            "validation": validation_metrics,
            "test": test_metrics,
        }

        model_path = (
            artifact_directory
            / "model.joblib"
        )

        metrics_path = (
            artifact_directory
            / "metrics.json"
        )

        feature_importances_path = (
            artifact_directory
            / "feature_importances.csv"
        )

        joblib.dump(
            pipeline,
            model_path,
        )

        metrics_path.write_text(
            json.dumps(
                metrics,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        save_feature_importances(
            pipeline=pipeline,
            destination=(
                feature_importances_path
            ),
        )

        model_parameters = (
            get_loggable_model_parameters(
                pipeline
            )
        )

        manifest = (
            log_common_run_metadata(
                model_name=model_name,
                parameters={
                    **model_parameters,
                    **training_metadata,
                    "threshold_strategy": (
                        "best_validation_f1"
                    ),
                },
                metrics={},
                tags={
                    "model_family": (
                        "tree_ensemble"
                    ),
                },
            )
        )

        log_dataset_input(
            train_features,
            manifest,
            "training",
        )

        log_dataset_input(
            validation_features,
            manifest,
            "validation",
        )

        log_dataset_input(
            test_features,
            manifest,
            "testing",
        )

        mlflow.log_metrics(
            flatten_metrics(metrics)
        )

        mlflow.log_artifact(
            str(metrics_path),
            artifact_path="evaluation",
        )

        mlflow.log_artifact(
            str(feature_importances_path),
            artifact_path="analysis",
        )

        log_sklearn_model(
            pipeline=pipeline,
            input_example=(
                train_features.head(5)
            ),
        )

        run_id = (
            mlflow.active_run()
            .info
            .run_id
        )

        write_run_reference(
            artifact_directory
            / "mlflow_run.json"
        )

    print("\nTreinamento concluído.")

    print(
        f"Modelo: {model_name}"
    )

    print(
        f"Run MLflow: {run_id}"
    )

    print(
        f"Threshold: "
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
        "\nArtefatos locais: "
        f"{artifact_directory}"
    )


if __name__ == "__main__":
    main()