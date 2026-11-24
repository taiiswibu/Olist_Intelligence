"""Retrospective delivery ranking; selection uses chronological development only."""
import hashlib
import json
import platform
from datetime import datetime, timezone
from functools import lru_cache
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
from sklearn.metrics import (average_precision_score, roc_auc_score, brier_score_loss,
    precision_score, recall_score, f1_score, confusion_matrix, precision_recall_curve)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler
from threadpoolctl import threadpool_limits
from .config import ROOT
from . import ml_features as shipping

NUMERIC = ["product_gmv", "freight", "item_count", "seller_count", "mean_weight_g", "category_count",
           "purchase_weekday", "purchase_hour", "approval_hours", "promised_days"]
CATEGORICAL = ["customer_state", "dominant_category"]
FEATURES = NUMERIC + CATEGORICAL
MODEL = ROOT / "models/delivery.joblib"
FEATURE_CACHE = ROOT / "models/delivery_features.joblib"
CONFIGS = {"prior": {}, "baseline_logistic": {}, "baseline_hist": {}, "shipping_logistic": {},
    "shipping_hist_small": {"max_leaf_nodes":8,"max_iter":180,"l2_regularization":10,"min_samples_leaf":60},
    "shipping_hist_medium": {"max_leaf_nodes":15,"max_iter":220,"l2_regularization":10,"min_samples_leaf":40},
    "shipping_hist_deep": {"max_leaf_nodes":31,"max_iter":220,"l2_regularization":20,"min_samples_leaf":60},
    "shipping_hist_regularized": {"max_leaf_nodes":15,"max_iter":160,"l2_regularization":30,"min_samples_leaf":120},
    "geo_hist_small": {"max_leaf_nodes":8,"max_iter":180,"l2_regularization":10,"min_samples_leaf":60},
    "geo_hist_medium": {"max_leaf_nodes":15,"max_iter":220,"l2_regularization":10,"min_samples_leaf":40},
    "geo_logistic": {}}
PROTOCOL = {
    "version": "precision-shipping-v3", "recall_floor": .30,
    "folds": [
        {"name":"jan","fit_end":"2018-01-01","start":"2018-01-01","end":"2018-02-01","known_before":"2018-03-01"},
        {"name":"mar","fit_end":"2018-03-01","start":"2018-03-01","end":"2018-04-01","known_before":"2018-05-01"},
        {"name":"may","fit_end":"2018-05-01","start":"2018-05-01","end":"2018-06-01","known_before":"2018-07-01"}],
    "selection": "Highest mean development precision at recall >= 0.30; tie mean AP then name.",
    "threshold_selection": "Highest precision among observed thresholds with recall >= 0.30; tie higher recall, then higher threshold. Each candidate/window separately.",
    "promotion_gate": "At least 5% relative mean precision gain over the best baseline; no precision regression against best baseline on latest May development.",
    "candidates": CONFIGS,
    "history_policy": "Only fit outcomes released strictly before min(order approval, fit cutoff); frozen for later cohorts. No validation/test labels.",
    "holdout_policy": "July 2018 was exposed previously. Replay once after selection and promotion gate; no fit, calibration, feature or threshold tuning on July."
}


def choose_threshold(y, prob, recall_floor=.30):
    precision, recall, thresholds = precision_recall_curve(y, prob)
    eligible = np.flatnonzero(recall[:-1] >= recall_floor)
    if not len(eligible):
        raise ValueError("No threshold meets the requested recall")
    i = max(eligible, key=lambda j: (precision[j], recall[j], thresholds[j]))
    return float(thresholds[i])


def choose_candidate(summary):
    return min(summary, key=lambda n: (-summary[n]["precision"], -summary[n]["pr_auc_ap"], n))


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
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1) if ordinal else OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    cat = make_pipeline(SimpleImputer(strategy="most_frequent"), encoder)
    if ordinal:
        num = SimpleImputer(strategy="median")
    return ColumnTransformer([("num", num, NUMERIC), ("cat", cat, CATEGORICAL)])


def candidate(name):
    enriched = name.startswith(("shipping_", "geo_"))
    extra = shipping.NUMERIC[:10] if name.startswith("geo_") else shipping.NUMERIC if enriched else []
    num = NUMERIC + extra
    cat = CATEGORICAL + (shipping.CATEGORICAL if enriched else [])
    if name == "prior":
        return make_pipeline(preprocessing(), DummyClassifier(strategy="prior")), num+cat
    if name == "baseline_logistic":
        return make_pipeline(preprocessing(), LogisticRegression(C=1,max_iter=500,random_state=42)), num+cat
    if name == "baseline_hist":
        model = HistGradientBoostingClassifier(max_iter=160,max_leaf_nodes=15,learning_rate=.06,l2_regularization=5,early_stopping=False,random_state=42)
        return make_pipeline(preprocessing(ordinal=True), model), num+cat
    if name in ("shipping_logistic", "geo_logistic"):
        prep = ColumnTransformer([("num",make_pipeline(SimpleImputer(strategy="median"),StandardScaler()),num),
            ("cat",make_pipeline(SimpleImputer(strategy="most_frequent"),OneHotEncoder(handle_unknown="ignore",sparse_output=False)),cat)])
        return make_pipeline(prep,LogisticRegression(C=1,max_iter=800,random_state=42)),num+cat
    prep = ColumnTransformer([("num","passthrough",num),("cat",make_pipeline(SimpleImputer(strategy="most_frequent"),
        OrdinalEncoder(handle_unknown="use_encoded_value",unknown_value=np.nan,max_categories=200)),cat)])
    model = HistGradientBoostingClassifier(**CONFIGS[name],learning_rate=.05,early_stopping=False,random_state=42,
        categorical_features=[False]*len(num)+[True]*len(cat))
    return make_pipeline(prep,model),num+cat


def eligible(frame):
    frame = frame.copy()
    if frame.order_id.duplicated().any():
        raise ValueError("Duplicate order_id invalidates the order-level evaluation")
    for c in ("approved_at","actual_delivery","estimated_delivery"):
        frame[c] = pd.to_datetime(frame[c],errors="coerce",format="mixed")
    return frame[frame.is_late.isin([0,1]) & frame.approved_at.notna() &
                 (frame.approval_hours>=0) & (frame.promised_days>=0)].sort_values(["approved_at","order_id"])


def development_split(frame, fold, min_rows=100):
    frame = eligible(frame)
    fit = frame[(frame.approved_at<fold["fit_end"]) & (frame.actual_delivery<fold["fit_end"]) & (frame.estimated_delivery<fold["fit_end"])]
    validation = frame[(frame.approved_at>=fold["start"]) & (frame.approved_at<fold["end"]) &
        (frame.actual_delivery<fold["known_before"]) & (frame.estimated_delivery<fold["known_before"])]
    if any(len(p)<min_rows or p.is_late.nunique()!=2 for p in (fit,validation)):
        raise ValueError("Need full original Olist data and both labels in every development window")
    return fit,validation


def promotion_gate(summary, latest, winner):
    baselines = ["baseline_logistic","baseline_hist"]
    mean_baseline = max(summary[n]["precision"] for n in baselines)
    latest_baseline = max(latest[n]["precision"] for n in baselines)
    return {"passed":summary[winner]["precision"]>=mean_baseline*1.05 and latest[winner]["precision"]>=latest_baseline,
        "mean_baseline_precision":mean_baseline,"latest_baseline_precision":latest_baseline,
        "mean_relative_precision_gain":summary[winner]["precision"]/mean_baseline-1}


def partition_summary(frame, features):
    columns = ["order_id","approved_at","actual_delivery","estimated_delivery","is_late"]+features
    return {"rows":len(frame),"positives":int(frame.is_late.sum()),"positive_rate":float(frame.is_late.mean()),
        "approval_min":frame.approved_at.min().isoformat(),"approval_max":frame.approved_at.max().isoformat(),
        "data_sha256":hashlib.sha256(frame[columns].to_csv(index=False,float_format="%.12g").encode()).hexdigest()}


def train():
    context,membership = shipping.load_context()
    dev = context[context.approved_at.notna() & (context.approved_at<"2018-06-01")].copy()
    dev_members = membership[membership.order_id.isin(dev.order_id)]
    development = {};partitions = {};models = {}
    with threadpool_limits(limits=4):
        for fold in PROTOCOL["folds"]:
            data = shipping.add_history(dev,dev_members,fold["fit_end"])
            fit,val = development_split(data,fold)
            print(f"Development {fold['name']}: fit={len(fit)}, validation={len(val)}",flush=True)
            development[fold["name"]] = {}
            for name in CONFIGS:
                model,features = candidate(name)
                model.fit(fit[features],fit.is_late.astype(int))
                prob = model.predict_proba(val[features])[:,1]
                threshold = choose_threshold(val.is_late.astype(int),prob,PROTOCOL["recall_floor"])
                development[fold["name"]][name] = metric(val.is_late.astype(int),prob,threshold)
                models[name] = {"model":model,"features":features,"threshold":threshold,"name":name}
            partitions[fold["name"]] = {"fit":len(fit),"validation":len(val)}
        summary = {name:{key:float(np.mean([d[name][key] for d in development.values()]))
            for key in ("precision","recall","pr_auc_ap","brier")} for name in CONFIGS}
        winner = choose_candidate(summary)
        gate = promotion_gate(summary,development["may"],winner)
        print(json.dumps({"frozen_winner":winner,"threshold":models[winner]["threshold"],"promotion_gate":gate}),flush=True)
        if not gate["passed"]:
            raise ValueError("Development improvement gate failed; existing model and report kept. Do not inspect July to choose another candidate.")
        all_data = shipping.add_history(context,membership,"2018-05-01")
        selected = models[winner];features = selected["features"]
        fit,val = development_split(all_data,PROTOCOL["folds"][-1])
        test = eligible(all_data)
        test = test[(test.approved_at>="2018-07-01") & (test.approved_at<"2018-08-01")]
        test_results = {name:metric(test.is_late.astype(int),m["model"].predict_proba(test[m["features"]])[:,1],m["threshold"]) for name,m in models.items()}
    MODEL.parent.mkdir(exist_ok=True)
    feature_next = FEATURE_CACHE.with_name("delivery_features.next.joblib")
    model_next = MODEL.with_name("delivery.next.joblib")
    joblib.dump({"version":shipping.VERSION,"frame":all_data.set_index("order_id")[features]},feature_next)
    cache_sha = hashlib.sha256(feature_next.read_bytes()).hexdigest()
    bundle = dict(selected,sklearn=sklearn.__version__,calibrated=False,protocol=PROTOCOL["version"],feature_cache_sha256=cache_sha)
    joblib.dump(bundle,model_next)
    report = {"winner":winner,"threshold":bundle["threshold"],"features":features,"calibrated":False,
        "trained_at_utc":datetime.now(timezone.utc).isoformat(),"protocol":PROTOCOL,"development":development,
        "development_partitions":partitions,"development_summary":summary,"promotion_gate":gate,
        "evaluation_kind":"replay_of_previously_exposed_july_2018_holdout","validation":development["may"],"test":test_results,
        "partitions":{name:partition_summary(p,features) for name,p in [("fit",fit),("validation",val),("test",test)]},
        "sklearn":sklearn.__version__,"python":platform.python_version(),
        "training_source_sha256_lf":hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode()).hexdigest(),
        "feature_source_sha256_lf":hashlib.sha256((ROOT/"olist/ml_features.py").read_text(encoding="utf-8").encode()).hexdigest(),
        "local_artifact":{"path":"models/delivery.joblib","sha256":hashlib.sha256(model_next.read_bytes()).hexdigest(),"tracked_in_git":False},
        "feature_cache":{"path":"models/delivery_features.joblib","sha256":cache_sha,"rows":len(all_data),"contains_labels":False,"tracked_in_git":False},
        "split":{"fit":"Latest fit: approvals and actual + promised dates before May 1, 2018; no refit after selection",
            "validation":"January/March/May chronological development; latest threshold from May, outcomes before July 1",
            "test":"July 2018 delivered/labeled orders; already exposed, regression replay only"},
        "prediction_time":"Order approval, assuming snapshot product/seller/customer/estimated-date fields were then available",
        "limitations":["Development metrics used for model/threshold selection are optimistic, not an independent test.",
            "The recall floor is a validation constraint, not a guarantee on July or future orders.",
            "July was exposed previously; replay cannot establish independent new quality improvement.",
            "Completed/labeled orders only, with observable-outcome selection bias and temporal distribution shift.",
            "Zip-center straight-line distance is approximate; snapshot attributes may have been revised after approval.",
            "Uncalibrated scores; no operational probability accuracy or business intervention cost claim.",
            "Local feature cache supports existing historical Olist orders; this is not a live ERP delivery model."]}
    feature_next.replace(FEATURE_CACHE);model_next.replace(MODEL)
    (ROOT/"reports/ml_evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"winner":winner,"test":test_results[winner]},indent=2))
    return report


@lru_cache(maxsize=2)
def _cached_features(path, expected_sha, mtime_ns, size):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected_sha:
        raise ValueError("Bộ đặc trưng không khớp model; chạy lại python manage.py train")
    return joblib.load(path)["frame"]


def predict(features):
    if not MODEL.exists():
        raise ValueError("Chưa có model. Chạy python manage.py train")
    bundle = joblib.load(MODEL)
    if bundle["sklearn"]!=sklearn.__version__:
        raise ValueError("Phiên bản scikit-learn khác bản train. Chạy lại python manage.py train")
    columns = bundle["features"]
    if bundle.get("feature_cache_sha256"):
        if not FEATURE_CACHE.exists():
            raise ValueError("Thiếu bộ đặc trưng vận chuyển; chạy lại python manage.py train")
        stat = FEATURE_CACHE.stat()
        cache = _cached_features(str(FEATURE_CACHE),bundle["feature_cache_sha256"],stat.st_mtime_ns,stat.st_size)
        order_id = features.get("order_id")
        if order_id not in cache.index:
            raise ValueError("Đơn chưa có đặc trưng trong snapshot huấn luyện; cần cập nhật dữ liệu và train lại")
        data = cache.loc[[order_id],columns].copy()
        for name in FEATURES:
            left,right = features.get(name),data.iloc[0][name]
            if (pd.isna(left) and pd.isna(right)) or (pd.notna(left) and pd.notna(right) and left==right):
                continue
            raise ValueError("Dữ liệu đơn đã đổi so với bộ đặc trưng; cần train lại")
    else:
        data = pd.DataFrame([{k:features.get(k) for k in columns}])
    for c in set(columns)-set(CATEGORICAL+shipping.CATEGORICAL):
        data[c] = pd.to_numeric(data[c],errors="coerce")
    for c in set(columns)&set(CATEGORICAL+shipping.CATEGORICAL):
        data[c] = data[c].fillna("unknown")
    with threadpool_limits(limits=2):
        risk = float(bundle["model"].predict_proba(data)[:,1][0])
    return {"risk_score":risk,"threshold":bundle["threshold"],"high_risk":risk>=bundle["threshold"],"model":bundle["name"],
        "calibrated":bundle.get("calibrated",False),"note":"Điểm chưa hiệu chỉnh xác suất; ngưỡng được chọn để giảm cảnh báo sai trên validation, không phải độ chính xác."}
