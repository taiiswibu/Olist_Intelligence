import pandas as pd
import pytest
from olist.ingest import build_facts
from olist.analytics import Filters, kpis, breakdown


def test_item_payment_fanout_and_reviews(raw):
    f, _ = build_facts(raw)
    a = f.set_index("order_id").loc["a"*32]
    assert a.product_gmv == 30
    assert a.paid_amount == 60
    assert a.item_count == 2
    assert a.review_score == 3
    assert len(f) == 3


def test_lateness_is_calendar_day_and_unknown_stays_unknown(raw):
    f, _ = build_facts(raw)
    assert list(f.is_late.fillna(-1)) == [0,1,-1]


def test_duplicate_primary_key_stops_ingest(raw):
    raw["orders"] = pd.concat([raw["orders"], raw["orders"].iloc[:1]])
    with pytest.raises(ValueError, match="Duplicate key"):
        build_facts(raw)


def test_delivered_gmv_denominators_and_state_filters(db):
    r = kpis(Filters())["values"]
    assert r["product_gmv"] == 70
    assert r["product_aov"] == 35
    assert r["late_delivery_rate"] == .5
    assert r["cancellation_rate"] == 1/3
    assert kpis(Filters(state="RJ"))["values"]["product_gmv"] == 0


def test_empty_range_no_division_by_zero(db):
    r = kpis(Filters(start="2017-01-01", end="2017-12-31"))["values"]
    assert r["orders"] == 0
    assert r["late_delivery_rate"] is None
    assert r["product_aov"] is None


def test_seller_orders_not_counted_per_item(db):
    sellers = breakdown("seller", Filters(), min_orders=1)["rows"]
    s1 = next(r for r in sellers if r["seller_id"] == "s1")
    assert s1["orders"] == 2
    assert s1["late_eligible"] == 1
    assert s1["product_gmv"] == 30


def test_categories_reconcile_delivered_gmv(db):
    assert sum(r["product_gmv"] for r in breakdown("category", Filters())["rows"]) == 70
