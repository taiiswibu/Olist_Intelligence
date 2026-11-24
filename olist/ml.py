"""Retrospective risk at order approval; outcomes and reviews excluded from features."""
import json
import platform
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss, precision_score, recall_score, f1_score, confusion_matrix
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
PROTOCOL = {
    "version": "chronological-calibration-v2",
    "fit_end": "2018-03-01",
    "calibration_end": "2018-05-01",
    "validation_end": "2018-06-01",
    "validation_outcomes_before": "2018-07-01",
    "test_start": "2018-07-01",
    "test_end": "2018-08-01",
    "selection": "Highest validation AP; equal AP to 12 decimals: lowest validation Brier, then name.",
    "threshold_selection": "Highest validation F1 on 0.01..0.99 by 0.01, separately per candidate; ties prefer higher threshold.",
    "calibration": "Sigmoid on disjoint chronological data; FrozenEstimator prevents refitting the base model.",
    "candidate_parameters": {"logistic": {"C": 1, "max_iter": 500, "random_state": 42},
        "hist_gradient_boosting": {"max_iter": 160, "max_leaf_nodes": 15, "learning_rate": .06,
                                   "l2_regularization": 5, "early_stopping": False, "random_state": 42}},
    "holdout_policy": "July 2018 was exposed previously. Replay only after validation selection; never fit, calibrate or select on it."
}


def chronological_split(df):
    df = df.copy()
    if df.order_id.duplicated().any():
        raise ValueError("Duplicate order_id would invalidate the order-level evaluation")
    for column in ("approved_at", "actual_delivery", "estimated_delivery"):
        df[column] = pd.to_datetime(df[column], errors="coerce", format="mixed")
    df = df[df.is_late.isin([0, 1]) & df.approved_at.notna() &
            (df.approval_hours >= 0) & (df.promised_days >= 0)].sort_values(["approved_at", "order_id"])
    def known_before(date):
        return (df.actual_delivery < date) & (df.estimated_delivery < date)
    p = PROTOCOL
    return {
        "fit": df[(df.approved_at < p["fit_end"]) & known_before(p["fit_end"])].copy(),
        "calibration": df[(df.approved_at >= p["fit_end"]) & (df.approved_at < p["calibration_end"]) &
                          known_before(p["calibration_end"])].copy(),
        "validation": df[(df.approved_at >= p["calibration_end"]) & (df.approved_at < p["validation_end"]) &
                         known_before(p["validation_outcomes_before"])].copy(),
        "test": df[(df.approved_at >= p["test_start"]) & (df.approved_at < p["test_end"])].copy()
    }


def choose_threshold(y, prob):
    return float(max(np.arange(1, 100) / 100,
                     key=lambda t: (f1_score(y, prob >= t, zero_division=0), t)))


def choose_candidate(validation):
    return min(validation, key=lambda n: (-round(validation[n]["pr_auc_ap"], 12), validation[n]["brier"], n))


def metric(y, prob, threshold):
    pred = prob >= threshold
    tn, fp, fn, tp = (int(x) for x in confusion_matrix(y, pred, labels=[0, 1]).ravel())
    return {"rows": len(y), "positive_rate": float(np.mean(y)), "threshold": float(threshold),
        "pr_auc_ap": float(average_precision_score(y, prob)), "roc_auc": float(roc_auc_score(y, prob)),
        "brier": float(brier_score_loss(y, prob)), "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)), "f1": float(f1_score(y, pred, zero_division=0)),
        "alerts": int(pred.sum()), "alert_rate": float(pred.mean()), "true_positives": tp,
        "false_positives": fp, "false_negatives": fn, "true_negatives": tn}


def preprocessing(ordinal=False):
    num = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
    cat = make_pipeline(SimpleImputer(strategy="most_frequent"), OneHotEncoder(handle_unknown="ignore", sparse_output=False))
    if ordinal:
        num = SimpleImputer(strategy="median")
        cat = make_pipeline(SimpleImputer(strategy="most_frequent"), OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1))
    return ColumnTransformer([("num", num, NUMERIC), ("cat", cat, CATEGORICAL)])


def fit_and_select(fit, calibration, validation):
    """No test argument: all fitting and decisions finish before holdout inference."""
    candidates = {
        "prior": make_pipeline(preprocessing(), DummyClassifier(strategy="prior")),
        "logistic": make_pipeline(preprocessing(), LogisticRegression(**PROTOCOL["candidate_parameters"]["logistic"])),
        "hist_gradient_boosting": make_pipeline(preprocessing(ordinal=True), HistGradientBoostingClassifier(
            **PROTOCOL["candidate_parameters"]["hist_gradient_boosting"])),
    }
    for name, model in list(candidates.items()):
        print(f"Training {name}: {len(fit)} records", flush=True)
        model.fit(fit[FEATURES], fit.is_late.astype(int))
        if name != "prior":
            calibrated = CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid")
            calibrated.fit(calibration[FEATURES], calibration.is_late.astype(int))
            candidates[name + "_sigmoid"] = calibrated
    results = {}
    for name, model in candidates.items():
        prob = model.predict_proba(validation[FEATURES])[:, 1]
        threshold = choose_threshold(validation.is_late.astype(int), prob)
        results[name] = metric(validation.is_late.astype(int), prob, threshold)
    return candidates, choose_candidate(results), results


def partition_summary(frame):
    columns = ["order_id", "approved_at", "actual_delivery", "estimated_delivery", "is_late"] + FEATURES
    digest = hashlib.sha256(frame[columns].to_csv(index=False, float_format="%.12g").encode()).hexdigest()
    return {"rows": len(frame), "positives": int(frame.is_late.sum()), "positive_rate": float(frame.is_late.mean()),
            "approval_min": frame.approved_at.min().isoformat(), "approval_max": frame.approved_at.max().isoformat(),
            "data_sha256": digest}


def train():
    parts = chronological_split(pd.DataFrame(rows("SELECT * FROM order_fact ORDER BY approved_at, order_id")))
    if any(len(frame) < 100 or frame.is_late.nunique() != 2 for frame in parts.values()):
        raise ValueError("Need at least 100 records and both labels in each chronological partition; use full original Olist data")
    with threadpool_limits(limits=4):
        candidates, winner, validation = fit_and_select(parts["fit"], parts["calibration"], parts["validation"])
        threshold = validation[winner]["threshold"]
        # Frozen selection. This is a replay of an exposed holdout, not a new test.
        print(json.dumps({"frozen_winner": winner, "threshold": threshold, "validation": validation}), flush=True)
        test = parts["test"]
        test_results = {name: metric(test.is_late.astype(int), m.predict_proba(test[FEATURES])[:, 1], validation[name]["threshold"])
                        for name, m in candidates.items()}
    MODEL.parent.mkdir(exist_ok=True)
    calibrated = winner.endswith("_sigmoid")
    bundle = {"model": candidates[winner], "threshold": threshold, "features": FEATURES, "name": winner,
              "sklearn": sklearn.__version__, "calibrated": calibrated, "protocol": PROTOCOL["version"]}
    joblib.dump(bundle, MODEL)
    report = {"winner": winner, "threshold": threshold, "features": FEATURES,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(), "protocol": PROTOCOL,
        "evaluation_kind": "replay_of_previously_exposed_july_2018_holdout", "calibrated": calibrated,
        "partitions": {name: partition_summary(frame) for name, frame in parts.items()},
        "training_source_sha256_lf": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode()).hexdigest(),
        "local_artifact": {"path": "models/delivery.joblib", "sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
                           "tracked_in_git": False},
        "sklearn": sklearn.__version__, "python": platform.python_version(),
        "prediction_time": "order approval; assumes item, product and promised delivery information already available",
        "split": {"fit": "approval before March 2018; actual + promised dates before March 1",
                  "calibration": "March-April 2018 approvals; actual + promised dates before May 1; disjoint from fit",
                  "validation": "May 2018 approvals with outcomes known by July 1",
                  "test": "July 2018 approvals; delivered and labeled orders only; exposed previously, replay only; no refit"},
        "validation": validation, "test": test_results,
        "limitations": ["Completed orders only; no accuracy claim for open/canceled orders or current business data.",
                         "Historical CSV cannot prove that estimated delivery dates and product attributes were not revised later.",
                         "Sigmoid calibration is fitted only on the separate calibration partition; operational probability accuracy is not established.",
                         "July 2018 has been exposed previously: these are regression results, not an independent new holdout.",
                         "F1 selects an experimental threshold, not a business-optimal intervention cost or capacity.",
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
            "calibrated": b.get("calibrated", False),
            "note": ("Điểm đã hiệu chỉnh sigmoid trên tập riêng; chưa xác minh xác suất trên dữ liệu vận hành."
                     if b.get("calibrated") else "Điểm chưa hiệu chỉnh xác suất; đánh giá hồi cứu, không cam kết dự báo thực tế.")}
