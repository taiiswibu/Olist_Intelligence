"""Order-level shipping context; history is released only after outcomes are known."""
from collections import defaultdict
import numpy as np
import pandas as pd

NUMERIC = ["distance_mean_km", "distance_max_km", "same_state_share", "geolocation_coverage",
           "volume_mean_cm3", "volume_max_cm3", "freight_per_item", "price_per_item", "freight_ratio",
           "promised_per_1000km", "seller_history_count", "seller_history_late_mean", "seller_history_late_max",
           "seller_history_days", "route_history_count", "route_history_late", "route_history_days", "promise_slack_days"]
CATEGORICAL = ["dominant_seller_state", "state_route", "customer_zip_region", "seller_zip_region"]
VERSION = "shipping-context-history-v1"


def geographic_centers(geo):
    geo = geo.loc[geo.geolocation_lat.between(-34, 6) & geo.geolocation_lng.between(-74, -34)]
    return geo.groupby("geolocation_zip_code_prefix")[["geolocation_lat", "geolocation_lng"]].median()


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = [np.radians(x) for x in [lat1, lon1, lat2, lon2]]
    a = np.sin((lat2-lat1)/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def shipping_context(facts, items, customers, sellers, products, geo):
    if facts.order_id.duplicated().any() or items.duplicated(["order_id", "order_item_id"]).any():
        raise ValueError("Shipping features require unique order and item grain")
    centers = geographic_centers(geo)
    customers = customers[["customer_id", "customer_zip_code_prefix"]].merge(
        centers, left_on="customer_zip_code_prefix", right_index=True, how="left", validate="many_to_one").rename(
        columns={"geolocation_lat":"customer_lat", "geolocation_lng":"customer_lon"})
    sellers = sellers[["seller_id", "seller_state", "seller_zip_code_prefix"]].merge(
        centers, left_on="seller_zip_code_prefix", right_index=True, how="left", validate="many_to_one").rename(
        columns={"geolocation_lat":"seller_lat", "geolocation_lng":"seller_lon"})
    base = facts.merge(customers, on="customer_id", how="left", validate="many_to_one")
    products = products[["product_id", "product_length_cm", "product_height_cm", "product_width_cm"]].copy()
    dimensions = products[["product_length_cm", "product_height_cm", "product_width_cm"]]
    products["volume_cm3"] = dimensions.prod(axis=1, min_count=3).where((dimensions>0).all(axis=1))
    item = items.drop(columns=["seller_state"], errors="ignore").merge(sellers, on="seller_id", how="left", validate="many_to_one")
    item = item.merge(products[["product_id", "volume_cm3"]], on="product_id", how="left", validate="many_to_one")
    item = item.merge(base[["order_id", "customer_state", "customer_lat", "customer_lon"]], on="order_id", how="left", validate="many_to_one")
    item["distance_km"] = haversine(item.customer_lat, item.customer_lon, item.seller_lat, item.seller_lon)
    item["same_state"] = (item.customer_state == item.seller_state).astype(float).where(item.seller_state.notna())
    agg = item.groupby("order_id").agg(distance_mean_km=("distance_km","mean"), distance_max_km=("distance_km","max"),
        same_state_share=("same_state","mean"), geolocation_coverage=("distance_km", "count"),
        volume_mean_cm3=("volume_cm3","mean"), volume_max_cm3=("volume_cm3","max"))
    # Pick the seller contributing most merchandise value, with a stable tie break.
    dominant = item.groupby(["order_id","seller_id","seller_state","seller_zip_code_prefix"], dropna=False, as_index=False).price.sum()
    dominant = dominant.sort_values(["order_id","price","seller_id"], ascending=[True,False,True]).drop_duplicates("order_id")
    base = base.merge(agg, on="order_id", how="left", validate="one_to_one")
    base = base.merge(dominant[["order_id","seller_state","seller_zip_code_prefix"]].rename(
        columns={"seller_state":"dominant_seller_state"}), on="order_id", how="left", validate="one_to_one")
    count = base.item_count.replace(0, np.nan)
    base["geolocation_coverage"] = base.geolocation_coverage/count
    base["freight_per_item"] = base.freight/count
    base["price_per_item"] = base.product_gmv/count
    base["freight_ratio"] = base.freight/base.product_gmv.replace(0,np.nan)
    base["promised_per_1000km"] = base.promised_days/(1+base.distance_mean_km/1000)
    base["state_route"] = base.dominant_seller_state.fillna("unknown")+":"+base.customer_state.fillna("unknown")
    for side in ("customer", "seller"):
        base[side+"_zip_region"] = base[side+"_zip_code_prefix"].astype("string").str.zfill(5).str[:2].fillna("unknown")
    return base, item[["order_id","seller_id","seller_state","customer_state"]].drop_duplicates(["order_id","seller_id"])


def historical_context(facts, order_sellers, cutoff):
    """Labels from fit only; strict release time also prevents own-row target leakage."""
    frame = facts.copy()
    for c in ("approved_at", "actual_delivery", "estimated_delivery"):
        frame[c] = pd.to_datetime(frame[c], errors="coerce", format="mixed")
    cutoff = pd.Timestamp(cutoff)
    source = frame.loc[frame.is_late.isin([0,1]) & (frame.approved_at < cutoff) &
                       (frame.actual_delivery < cutoff) & (frame.estimated_delivery < cutoff)].copy()
    source["available_at"] = pd.concat([source.actual_delivery, source.estimated_delivery.dt.normalize()+pd.Timedelta(days=1)], axis=1).max(axis=1)
    source["days"] = ((source.actual_delivery-source.approved_at).dt.total_seconds()/86400).clip(lower=0)
    events = source[["order_id","available_at","is_late","days"]].merge(order_sellers, on="order_id", validate="one_to_many")
    events = list(events.sort_values(["available_at","order_id","seller_id"]).itertuples(index=False))
    membership = defaultdict(list)
    for member in order_sellers.itertuples(index=False):
        membership[member.order_id].append(member)
    seller_stats = defaultdict(lambda:[0,0.,0.]);route_stats = defaultdict(lambda:[0,0.,0.])
    cursor = 0; output = []
    def update(stats, key, event):
        value=stats[key];value[0]+=1;value[1]+=event.is_late;value[2]+=event.days
    def read(stats,key):
        n,late,days=stats[key]
        return n,(late+.5)/(n+10),days/n if n else np.nan
    for order in frame.sort_values(["approved_at","order_id"],na_position="first").itertuples(index=False):
        when = min(order.approved_at,cutoff) if pd.notna(order.approved_at) else pd.Timestamp.min
        while cursor<len(events) and events[cursor].available_at < when:
            event=events[cursor];update(seller_stats,event.seller_id,event)
            update(route_stats,(event.seller_state,event.customer_state),event);cursor+=1
        members=membership.get(order.order_id,[])
        sr=[read(seller_stats,x.seller_id) for x in members]
        rr=[read(route_stats,(x.seller_state,x.customer_state)) for x in members]
        mean=lambda values:float(np.mean(values)) if values else np.nan
        valid_mean=lambda values:mean([v for v in values if np.isfinite(v)])
        days=valid_mean([v[2] for v in sr])
        output.append({"order_id":order.order_id,"seller_history_count":mean([v[0] for v in sr]),
            "seller_history_late_mean":mean([v[1] for v in sr]),"seller_history_late_max":max([v[1] for v in sr],default=np.nan),
            "seller_history_days":days,"route_history_count":mean([v[0] for v in rr]),
            "route_history_late":mean([v[1] for v in rr]),"route_history_days":valid_mean([v[2] for v in rr]),
            "promise_slack_days":order.promised_days-days})
    return pd.DataFrame(output)


def load_context():
    from .database import rows
    from .ingest import read_raw
    facts=pd.DataFrame(rows("SELECT * FROM order_fact ORDER BY approved_at, order_id"))
    items=pd.DataFrame(rows("SELECT * FROM item_fact ORDER BY order_id, order_item_id"))
    return shipping_context(facts,items,read_raw("customers"),read_raw("sellers"),read_raw("products"),read_raw("geolocation"))


def add_history(context, membership, cutoff):
    return context.merge(historical_context(context,membership,cutoff),on="order_id",validate="one_to_one")
