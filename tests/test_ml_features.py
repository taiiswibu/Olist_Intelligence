import numpy as np
import pandas as pd
from olist import ml_features as mf


def test_history_excludes_own_future_and_validation_outcomes():
    facts = pd.DataFrame([
        dict(order_id="a",approved_at="2018-01-01",actual_delivery="2018-01-10",estimated_delivery="2018-01-05",is_late=1,promised_days=4),
        dict(order_id="b",approved_at="2018-01-10",actual_delivery="2018-01-30",estimated_delivery="2018-01-20",is_late=1,promised_days=10),
        dict(order_id="c",approved_at="2018-01-11",actual_delivery="2018-02-05",estimated_delivery="2018-02-01",is_late=1,promised_days=21),
        dict(order_id="d",approved_at="2018-02-01",actual_delivery="2018-02-08",estimated_delivery="2018-02-10",is_late=0,promised_days=9),
    ])
    members = pd.DataFrame([dict(order_id=x,seller_id="s",seller_state="SP",customer_state="RJ") for x in "abcd"])
    result = mf.historical_context(facts,members,"2018-01-15").set_index("order_id")
    assert result.seller_history_count.to_dict()=={"a":0,"b":0,"c":1,"d":1}
    assert result.loc["a","seller_history_late_mean"]==.05
    assert result.loc["c","seller_history_late_mean"]==1.5/11
    # Even completed validation/test outcomes cannot update the frozen history.
    changed=facts.copy();changed.loc[changed.order_id.isin(["b","c","d"]),"is_late"]=0
    pd.testing.assert_frame_equal(result,mf.historical_context(changed,members,"2018-01-15").set_index("order_id"))
    own_changed=facts.copy();own_changed.loc[own_changed.order_id=="a","is_late"]=0
    own=mf.historical_context(own_changed,members,"2018-01-15").set_index("order_id")
    assert own.loc["a","seller_history_late_mean"]==result.loc["a","seller_history_late_mean"]


def test_distance_and_volume_preserve_order_grain_and_missing_geography():
    facts=pd.DataFrame([dict(order_id="a",customer_id="c1",customer_state="SP",item_count=2,freight=20,product_gmv=100,promised_days=10),
                        dict(order_id="b",customer_id="c2",customer_state="SP",item_count=1,freight=10,product_gmv=50,promised_days=10)])
    items=pd.DataFrame([dict(order_id=order,order_item_id=i,seller_id="s",product_id="p",price=50) for order,i in [("a",1),("a",2),("b",1)]])
    customers=pd.DataFrame([dict(customer_id="c1",customer_zip_code_prefix="00001"),dict(customer_id="c2",customer_zip_code_prefix="99999")])
    sellers=pd.DataFrame([dict(seller_id="s",seller_state="RJ",seller_zip_code_prefix="00002")])
    products=pd.DataFrame([dict(product_id="p",product_length_cm=10,product_height_cm=2,product_width_cm=3)])
    geo=pd.DataFrame([dict(geolocation_zip_code_prefix=z,geolocation_lat=0,geolocation_lng=lon) for z,lon in [("00001",-40),("00001",-40),("00002",-41)]])
    context,members=mf.shipping_context(facts,items,customers,sellers,products,geo)
    context=context.set_index("order_id")
    assert len(context)==2 and len(members)==2
    assert np.isclose(context.loc["a","distance_mean_km"],111.19508)
    assert context.loc["a","volume_mean_cm3"]==60
    assert context.loc["a","geolocation_coverage"]==1
    assert context.loc["b","geolocation_coverage"]==0
    assert np.isnan(context.loc["b","distance_mean_km"])
    assert context.loc["a","state_route"]=="RJ:SP"


def test_geography_drops_invalid_coordinates_before_zip_aggregation():
    geo=pd.DataFrame([dict(geolocation_zip_code_prefix="00001",geolocation_lat=0,geolocation_lng=-40),
                      dict(geolocation_zip_code_prefix="00001",geolocation_lat=80,geolocation_lng=20)])
    centers=mf.geographic_centers(geo)
    assert centers.loc["00001","geolocation_lat"]==0
    assert centers.loc["00001","geolocation_lng"]==-40
