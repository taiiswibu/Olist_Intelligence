"""Download the original public Olist archive and build grain-safe analytical facts."""
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import httpx
import numpy as np
import pandas as pd
from sqlalchemy import text
from .config import ROOT
from .database import engine

SOURCE = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"
DOWNLOAD = "https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce"
FILES = {
    "orders": "olist_orders_dataset.csv", "customers": "olist_customers_dataset.csv",
    "items": "olist_order_items_dataset.csv", "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv", "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv", "geolocation": "olist_geolocation_dataset.csv",
    "translation": "product_category_name_translation.csv",
}


def download():
    raw = ROOT / "data/raw"
    raw.mkdir(parents=True, exist_ok=True)
    if all((raw / f).exists() for f in FILES.values()):
        print("9 CSV already present; keeping existing source files.")
        return
    archive = raw / "olist_download.zip.part"
    print("Downloading original Kaggle archive (~45 MB)...", flush=True)
    try:
        with httpx.stream("GET", DOWNLOAD, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with archive.open("wb") as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
        with zipfile.ZipFile(archive) as z:
            found = {Path(n).name: n for n in z.namelist()}
            missing = set(FILES.values()) - set(found)
            if missing:
                raise ValueError(f"Archive missing files: {sorted(missing)}")
            # Never extract arbitrary member paths supplied by an archive.
            for filename in FILES.values():
                target = raw / filename
                if not target.exists():
                    with z.open(found[filename]) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    except Exception as exc:
        raise RuntimeError("Cannot download Olist. Download ZIP from the Kaggle link in README and place its 9 CSV files in data/raw/. No synthetic data substituted.") from exc
    finally:
        archive.unlink(missing_ok=True)


def read_raw(name):
    return pd.read_csv(ROOT / "data/raw" / FILES[name], dtype={
        "customer_zip_code_prefix": str, "seller_zip_code_prefix": str,
        "geolocation_zip_code_prefix": str,
    })


def build_facts(data):
    o, c, i, p, rv, pr, s, tr = (data[k].copy() for k in ["orders", "customers", "items", "payments", "reviews", "products", "sellers", "translation"])
    for name, frame, key in [("orders", o, ["order_id"]), ("customers", c, ["customer_id"]),
                             ("items", i, ["order_id", "order_item_id"]), ("products", pr, ["product_id"]),
                             ("sellers", s, ["seller_id"]), ("translation", tr, ["product_category_name"])]:
        if frame.duplicated(key).any():
            raise ValueError(f"Duplicate key in {name}: {key}")
    items = i.merge(pr, on="product_id", how="left", validate="many_to_one")
    items = items.merge(tr, on="product_category_name", how="left", validate="many_to_one")
    items["category"] = items["product_category_name_english"].fillna(items["product_category_name"]).fillna("unknown")
    items = items.merge(s[["seller_id", "seller_state"]], on="seller_id", how="left", validate="many_to_one")
    agg = items.groupby("order_id").agg(product_gmv=("price", "sum"), freight=("freight_value", "sum"),
        item_count=("order_item_id", "count"), seller_count=("seller_id", "nunique"),
        mean_weight_g=("product_weight_g", "mean"), category_count=("category", "nunique")).reset_index()
    # Deterministic most valuable category, breaking value ties lexicographically.
    cat = items.groupby(["order_id", "category"], as_index=False)["price"].sum()
    cat = cat.sort_values(["order_id", "price", "category"], ascending=[True, False, True]).drop_duplicates("order_id")
    agg = agg.merge(cat[["order_id", "category"]].rename(columns={"category": "dominant_category"}), on="order_id", validate="one_to_one")
    payments = p.groupby("order_id", as_index=False).agg(paid_amount=("payment_value", "sum"))
    reviews = rv.groupby("order_id", as_index=False).agg(review_score=("review_score", "mean"), review_count=("review_id", "size"))
    f = o.merge(c, on="customer_id", how="left", validate="many_to_one")
    for frame in [agg, payments, reviews]:
        f = f.merge(frame, on="order_id", how="left", validate="one_to_one")
    rename = {"order_purchase_timestamp": "purchase_at", "order_approved_at": "approved_at",
              "order_delivered_customer_date": "actual_delivery", "order_estimated_delivery_date": "estimated_delivery"}
    f = f.rename(columns=rename)
    for col in list(rename.values()):
        f[col] = pd.to_datetime(f[col], errors="coerce")
    f["purchase_date"] = f.purchase_at.dt.strftime("%Y-%m-%d")
    f["purchase_month"] = f.purchase_at.dt.strftime("%Y-%m")
    f["purchase_weekday"] = f.purchase_at.dt.day_of_week
    f["purchase_hour"] = f.purchase_at.dt.hour
    f["approval_hours"] = (f.approved_at - f.purchase_at).dt.total_seconds() / 3600
    f["promised_days"] = (f.estimated_delivery.dt.normalize() - f.approved_at.dt.normalize()).dt.days
    f["actual_delivery_days"] = (f.actual_delivery - f.purchase_at).dt.total_seconds() / 86400
    known = (f.order_status == "delivered") & f.actual_delivery.notna() & f.estimated_delivery.notna()
    f["is_late"] = np.nan
    f.loc[known, "is_late"] = (f.loc[known, "actual_delivery"].dt.normalize() > f.loc[known, "estimated_delivery"].dt.normalize()).astype(int)
    for col in ["product_gmv", "freight", "item_count", "seller_count", "category_count"]:
        f[col] = f[col].fillna(0)
    f["dominant_category"] = f["dominant_category"].fillna("unknown")
    keep = ["order_id", "customer_id", "customer_unique_id", "customer_state", "customer_city", "order_status",
            "purchase_at", "approved_at", "actual_delivery", "estimated_delivery", "purchase_date", "purchase_month",
            "purchase_weekday", "purchase_hour", "approval_hours", "promised_days", "actual_delivery_days", "is_late",
            "product_gmv", "freight", "paid_amount", "item_count", "seller_count", "mean_weight_g", "category_count",
            "dominant_category", "review_score", "review_count"]
    for col in ["purchase_at", "approved_at", "actual_delivery", "estimated_delivery"]:
        f[col] = f[col].dt.strftime("%Y-%m-%d %H:%M:%S").where(f[col].notna(), None)
    item_keep = ["order_id", "order_item_id", "product_id", "seller_id", "price", "freight_value", "category", "seller_state"]
    return f[keep], items[item_keep]


def ingest():
    data = {name: read_raw(name) for name in FILES if name != "geolocation"}
    facts, items = build_facts(data)
    if not items.order_id.isin(facts.order_id).all():
        raise ValueError("Orphan item order IDs")
    report = {"source": SOURCE, "license": "CC BY-NC-SA 4.0", "built_at": datetime.now(timezone.utc).isoformat(),
              "timezone": "Source unspecified; timestamps kept naive", "files": {}}
    for name, filename in FILES.items():
        path = ROOT / "data/raw" / filename
        n = len(data[name]) if name in data else sum(len(x) for x in pd.read_csv(path, chunksize=100000))
        report["files"][filename] = {"rows": n, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    report["checks"] = {"orders": len(facts), "items": len(items), "order_id_unique": bool(facts.order_id.is_unique),
        "raw_item_gmv": round(float(data["items"].price.sum()), 2), "fact_item_gmv": round(float(facts.product_gmv.sum()), 2),
        "raw_payments": round(float(data["payments"].payment_value.sum()), 2), "fact_payments": round(float(facts.paid_amount.sum()), 2),
        "late_eligible": int(facts.is_late.notna().sum()), "late_orders": int(facts.is_late.fillna(0).sum()),
        "purchase_min": facts.purchase_date.min(), "purchase_max": facts.purchase_date.max()}
    for a, b in [("raw_item_gmv", "fact_item_gmv"), ("raw_payments", "fact_payments")]:
        if abs(report["checks"][a] - report["checks"][b]) > .01:
            raise ValueError(f"Reconciliation failed: {a}/{b}")
    with engine().begin() as conn:
        facts.to_sql("order_fact", conn, if_exists="replace", index=False, chunksize=2000)
        items.to_sql("item_fact", conn, if_exists="replace", index=False, chunksize=2000)
        conn.execute(text("CREATE UNIQUE INDEX ix_order_id ON order_fact(order_id)"))
        conn.execute(text("CREATE INDEX ix_purchase_date ON order_fact(purchase_date)"))
        conn.execute(text("CREATE INDEX ix_item_order ON item_fact(order_id)"))
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/data_quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["checks"], indent=2))
    return report
