"""Retrospective risk at order approval; outcomes and reviews excluded from features."""
import json
import platform
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss, precision_score, recall_score, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler
from threadpoolctl import threadpool_limits
from .config import ROOT
from .database import rows

NUMERIC = ["product_gmv", "freight", "item_count", "seller_count", "mean_weight_g", "category_count",
           "purchase_weekday", "purchase_hour", "approval_hours", "promised_days"]
CATEGORICAL = ["customer_state", "dominant_category"]
FEATURES = NUMERIC + CATEGORICAL
MODEL = ROOT / "models/delivery.joblib"


def metric(y, prob, threshold):
    pred = prob >= threshold
    return {"rows": len(y), "positive_rate": float(np.mean(y)), "threshold": float(threshold),
        "pr_auc_ap": float(average_precision_score(y, prob)), "roc_auc": float(roc_auc_score(y, prob)),
        "brier": float(brier_score_loss(y, prob)), "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)), "f1": float(f1_score(y, pred, zero_division=0))}


def train():
    df = pd.DataFrame(rows("SELECT * FROM order_fact ORDER BY approved_at, order_id"))
    df = df[(df.is_late.notna()) & df.approved_at.notna() & (df.approval_hours >= 0) & (df.promised_days >= 0)].copy()
    # All training labels must be observable before the next evaluation window.
    # Outcome-known split uses both actual completion and promised calendar day.
    train = df[(df.approved_at < "2018-05-01") & (df.actual_delivery < "2018-05-01") & (df.estimated_delivery < "2018-05-01")]
    val = df[(df.approved_at >= "2018-05-01") & (df.approved_at < "2018-06-01") &
             (df.actual_delivery < "2018-07-01") & (df.estimated_delivery < "2018-07-01")]
    test = df[(df.approved_at >= "2018-07-01") & (df.approved_at < "2018-08-01")]
    if min(len(train), len(val), len(test)) < 100:
        raise ValueError("Not enough records in chronological split; download full original dataset")
    X, y = train[FEATURES], train.is_late.astype(int)
    num = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
    cat = make_pipeline(SimpleImputer(strategy="most_frequent"), OneHotEncoder(handle_unknown="ignore", sparse_output=False))
    prep = ColumnTransformer([("num", num, NUMERIC), ("cat", cat, CATEGORICAL)])
    ordinal = ColumnTransformer([
        ("num", SimpleImputer(strategy="median"), NUMERIC),
        ("cat", make_pipeline(SimpleImputer(strategy="most_frequent"), OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)), CATEGORICAL)])
    candidates = {
        "prior": make_pipeline(prep, DummyClassifier(strategy="prior")),
        "logistic": make_pipeline(prep, LogisticRegression(max_iter=500, C=1, random_state=42)),
        "hist_gradient_boosting": make_pipeline(ordinal, HistGradientBoostingClassifier(
            max_iter=160, max_leaf_nodes=15, learning_rate=.06, l2_regularization=5,
            early_stopping=False, random_state=42)),
    }
    validation = {}
    with threadpool_limits(limits=4):
        for name, model in candidates.items():
            print(f"Training {name}: {len(train)} records", flush=True)
            model.fit(X, y)
            validation[name] = metric(val.is_late.astype(int), model.predict_proba(val[FEATURES])[:, 1], .5)
        # Choose model and threshold on validation only. Freeze before one holdout pass.
        winner = max(candidates, key=lambda n: validation[n]["pr_auc_ap"])
        model = candidates[winner]
        pv = model.predict_proba(val[FEATURES])[:, 1]
        thresholds = np.linspace(.05, .5, 46)
        threshold = float(max(thresholds, key=lambda t: f1_score(val.is_late.astype(int), pv >= t, zero_division=0)))
        test_results = {name: metric(test.is_late.astype(int), m.predict_proba(test[FEATURES])[:, 1], threshold if name == winner else .5)
                        for name, m in candidates.items()}
    MODEL.parent.mkdir(exist_ok=True)
    bundle = {"model": model, "threshold": threshold, "features": FEATURES, "name": winner, "sklearn": sklearn.__version__}
    joblib.dump(bundle, MODEL)
    report = {"winner": winner, "threshold": threshold, "features": FEATURES,
        "sklearn": sklearn.__version__, "python": platform.python_version(),
        "prediction_time": "order approval; assumes item, product and promised delivery information already available",
        "split": {"train": "approval before May 2018; actual + promised dates before May 1",
                  "validation": "May 2018 approvals with outcomes known by July 1",
                  "test": "July 2018 approvals; delivered and labeled orders only; no refit"},
        "validation": validation, "test": test_results,
        "limitations": ["Completed orders only; no accuracy claim for open/canceled orders or current business data.",
                         "Historical CSV cannot prove that estimated delivery dates and product attributes were not revised later.",
                         "Risk scores are uncalibrated; no probability calibration claim.",
                         "Changing cohorts and observable-outcome filtering can introduce selection bias."]}
    (ROOT / "reports/ml_evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"winner": winner, "test": test_results[winner]}, indent=2))
    return report


def predict(features):
    if not MODEL.exists():
        raise ValueError("Chưa có model. Chạy python manage.py train")
    # Only load the artifact trained locally by this project.
    b = joblib.load(MODEL)
    if b["sklearn"] != sklearn.__version__:
        raise ValueError("Phiên bản scikit-learn khác bản train. Chạy lại python manage.py train")
    data = pd.DataFrame([{k: features.get(k) for k in FEATURES}])
    for c in NUMERIC:
        data[c] = pd.to_numeric(data[c], errors="coerce")
    for c in CATEGORICAL:
        data[c] = data[c].fillna("unknown")
    with threadpool_limits(limits=2):
        risk = float(b["model"].predict_proba(data)[:, 1][0])
    return {"risk_score": risk, "threshold": b["threshold"], "high_risk": risk >= b["threshold"], "model": b["name"],
            "note": "Điểm rủi ro chưa hiệu chỉnh xác suất; đánh giá hồi cứu, không cam kết dự báo thực tế."}
