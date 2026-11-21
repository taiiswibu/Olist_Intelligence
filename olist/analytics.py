from datetime import date
from pydantic import BaseModel, Field, model_validator
from .database import rows


class Filters(BaseModel):
    start: date = date(2017, 1, 1)
    end: date = date(2018, 8, 31)
    state: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")

    @model_validator(mode="after")
    def ordered(self):
        if self.start > self.end:
            raise ValueError("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc")
        return self

    def params(self):
        return {"start": str(self.start), "end": str(self.end), "state": self.state}


WHERE = "o.purchase_date >= :start AND o.purchase_date <= :end AND (:state IS NULL OR o.customer_state = :state)"
KPI_SQL = f"""SELECT COUNT(*) AS orders,
 SUM(CASE WHEN order_status='delivered' THEN 1 ELSE 0 END) AS delivered_orders,
 SUM(CASE WHEN order_status='delivered' THEN product_gmv ELSE 0 END) AS product_gmv,
 SUM(CASE WHEN order_status='delivered' THEN freight ELSE 0 END) AS freight,
 SUM(CASE WHEN order_status='canceled' THEN 1 ELSE 0 END) AS canceled_orders,
 COUNT(is_late) AS late_eligible, SUM(COALESCE(is_late,0)) AS late_orders
 FROM order_fact o WHERE {WHERE}"""


def kpis(filters: Filters):
    r = rows(KPI_SQL, filters.params())[0]
    for key in r:
        r[key] = r[key] or 0
    r["product_aov"] = r["product_gmv"] / r["delivered_orders"] if r["delivered_orders"] else None
    r["cancellation_rate"] = r["canceled_orders"] / r["orders"] if r["orders"] else None
    r["late_delivery_rate"] = r["late_orders"] / r["late_eligible"] if r["late_eligible"] else None
    return {"values": r, "filters": filters.model_dump(mode="json"), "currency": "BRL", "sql": KPI_SQL,
            "definition": "GMV/AOV: hàng hóa của đơn delivered, không gồm phí vận chuyển. Giao trễ: ngày giao thực tế sau ngày hẹn, trên đơn delivered đủ hai ngày."}


def breakdown(kind, filters: Filters, min_orders=20):
    if kind == "monthly":
        sql = f"""SELECT purchase_month AS month, COUNT(*) AS orders,
          SUM(CASE WHEN order_status='delivered' THEN product_gmv ELSE 0 END) AS product_gmv,
          COUNT(is_late) AS late_eligible, SUM(COALESCE(is_late,0)) AS late_orders
          FROM order_fact o WHERE {WHERE} GROUP BY purchase_month ORDER BY month"""
    elif kind == "category":
        sql = f"""SELECT i.category, SUM(i.price) AS product_gmv, COUNT(DISTINCT o.order_id) AS orders
          FROM item_fact i JOIN order_fact o ON i.order_id=o.order_id
          WHERE {WHERE} AND o.order_status='delivered'
          GROUP BY i.category ORDER BY product_gmv DESC LIMIT 15"""
    elif kind == "seller":
        sql = f"""SELECT i.seller_id, COUNT(DISTINCT o.order_id) AS orders,
          COUNT(DISTINCT CASE WHEN o.is_late IS NOT NULL THEN o.order_id END) AS late_eligible,
          COUNT(DISTINCT CASE WHEN o.is_late=1 THEN o.order_id END) AS late_orders,
          SUM(CASE WHEN o.order_status='delivered' THEN i.price ELSE 0 END) AS product_gmv
          FROM item_fact i JOIN order_fact o ON i.order_id=o.order_id WHERE {WHERE}
          GROUP BY i.seller_id HAVING COUNT(DISTINCT o.order_id)>=:min_orders
          ORDER BY late_orders DESC, orders DESC LIMIT 20"""
    elif kind == "state":
        sql = f"""SELECT customer_state AS state, COUNT(*) AS orders,
          COUNT(is_late) AS late_eligible, SUM(COALESCE(is_late,0)) AS late_orders,
          SUM(CASE WHEN order_status='delivered' THEN product_gmv ELSE 0 END) AS product_gmv
          FROM order_fact o WHERE {WHERE} GROUP BY customer_state
          HAVING COUNT(is_late)>=:min_orders ORDER BY late_orders DESC"""
    else:
        raise ValueError("Unknown breakdown")
    result = rows(sql, {**filters.params(), "min_orders": min_orders})
    for r in result:
        if "late_eligible" in r:
            r["late_rate"] = float(r["late_orders"] or 0) / r["late_eligible"] if r["late_eligible"] else None
    return {"rows": result, "sql": sql, "filters": filters.model_dump(mode="json")}


def lookup_order(order_id):
    return rows("SELECT * FROM order_fact WHERE order_id=:id", {"id": order_id})


def date_range():
    return rows("SELECT MIN(purchase_date) AS start, MAX(purchase_date) AS end, COUNT(*) AS orders FROM order_fact")[0]
