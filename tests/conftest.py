import pandas as pd
import pytest
from olist.ingest import build_facts


@pytest.fixture
def raw():
    return {
      "orders": pd.DataFrame([
        {"order_id":"a"*32,"customer_id":"c1","order_status":"delivered","order_purchase_timestamp":"2018-01-01 12:00:00","order_approved_at":"2018-01-01 13:00:00","order_delivered_customer_date":"2018-01-10 22:00:00","order_estimated_delivery_date":"2018-01-10 00:00:00"},
        {"order_id":"b"*32,"customer_id":"c2","order_status":"delivered","order_purchase_timestamp":"2018-01-02 12:00:00","order_approved_at":"2018-01-02 13:00:00","order_delivered_customer_date":"2018-01-11 01:00:00","order_estimated_delivery_date":"2018-01-10 00:00:00"},
        {"order_id":"c"*32,"customer_id":"c3","order_status":"canceled","order_purchase_timestamp":"2018-01-02 12:00:00","order_approved_at":None,"order_delivered_customer_date":None,"order_estimated_delivery_date":"2018-01-10 00:00:00"},
      ]),
      "customers": pd.DataFrame([{"customer_id":f"c{x}","customer_unique_id":"same" if x<3 else "other","customer_city":"city","customer_state":"SP" if x<3 else "RJ"} for x in range(1,4)]),
      "items": pd.DataFrame([
        {"order_id":"a"*32,"order_item_id":1,"product_id":"p1","seller_id":"s1","price":10.,"freight_value":2.},
        {"order_id":"a"*32,"order_item_id":2,"product_id":"p2","seller_id":"s1","price":20.,"freight_value":3.},
        {"order_id":"b"*32,"order_item_id":1,"product_id":"p1","seller_id":"s2","price":40.,"freight_value":4.},
        {"order_id":"c"*32,"order_item_id":1,"product_id":"p1","seller_id":"s1","price":50.,"freight_value":5.},
      ]),
      "payments": pd.DataFrame([{"order_id":"a"*32,"payment_value":x} for x in [10.,20.,30.]] + [{"order_id":"b"*32,"payment_value":44.}]),
      "reviews": pd.DataFrame([{"order_id":"a"*32,"review_id":"rv","review_score":1}, {"order_id":"a"*32,"review_id":"rv2","review_score":5}]),
      "products": pd.DataFrame([{"product_id":"p1","product_category_name":"cat1","product_weight_g":500}, {"product_id":"p2","product_category_name":"cat2","product_weight_g":200}]),
      "sellers": pd.DataFrame([{"seller_id":"s1","seller_state":"SP"}, {"seller_id":"s2","seller_state":"MG"}]),
      "translation": pd.DataFrame([{"product_category_name":"cat1","product_category_name_english":"books"}, {"product_category_name":"cat2","product_category_name_english":"toys"}]),
    }


@pytest.fixture
def db(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "analytics.db"))
    monkeypatch.setenv("APP_TOKEN", "local-test-token")
    monkeypatch.setenv("LLM_PROVIDERS", "")
    monkeypatch.setenv("RAG_MODE", "lexical")
    from olist import database
    monkeypatch.setattr(database, "ROOT", tmp_path)
    (tmp_path / "data/processed").mkdir(parents=True)
    f, i = build_facts(raw)
    with database.engine().begin() as conn:
        f.to_sql("order_fact", conn, index=False)
        i.to_sql("item_fact", conn, index=False)
    return f, i
