from typing import Literal

from sklearn.base import BaseEstimator
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

ModelName = Literal["random_forest", "xgboost"]

def create_random_forest(*, random_state: int = 42, n_jobs: int = -1) -> RandomForestClassifier:
    """Cria o modelo inicial de Random Forest."""

    return RandomForestClassifier(
        n_estimators=500,
        criterion="gini",
        max_depth=16,
        min_samples_split=10,
        min_samples_leaf=4,
        max_features='sqrt',
        class_weight='balanced_subsample',
        bootstrap=True,
        max_samples=0.8,
        oob_score=True,
        n_jobs=n_jobs,
        random_state=random_state
    )


def create_xgboost(*, scale_pos_weight: float, random_state: int = 42, n_jobs: int = -1) -> XGBClassifier:
    """Cria o modelo inicial XGBoost"""

    if scale_pos_weight <= 0:
        raise ValueError(
            "scale_pos_weight deve ser maior que zero"
        )

    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        n_estimators=1200,
        learning_rate=0.03,
        max_depth=6,
        min_child_weight=5,
        gamma=0.0,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=2.0,
        scale_pos_weight=scale_pos_weight,
        tree_method="hist",
        early_stopping_rounds=75,
        n_jobs=n_jobs,
        random_state=random_state
    )


def create_tree_model(
        model_name: ModelName,
        *,
        scale_pos_weight: float | None = None,
        random_state: int = 42,
        n_jobs: int = -1,
) -> BaseEstimator:
    """Cria um dos modelos a partir do seu nome."""

    if model_name == "random_forest":
        return create_random_forest(
            random_state=random_state,
            n_jobs=n_jobs
        )

    if model_name == "xgboost":
        if scale_pos_weight is None:
            raise ValueError(
                "scale_pos_weight é obrigatório para o XGBoost."
            )

        return create_xgboost(
            scale_pos_weight=scale_pos_weight,
            random_state=random_state,
            n_jobs=n_jobs,
        )

    raise ValueError(
        f"Modelo desconhecido: {model_name}"
    )