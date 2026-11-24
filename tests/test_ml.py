import hashlib
import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from threadpoolctl import threadpool_limits
from olist import ml,ml_features as shipping


def test_development_split_enforces_time_and_observable_labels():
    def row(order,approval,actual,promised,label):
        return dict(order_id=order,approved_at=approval,actual_delivery=actual,
                    estimated_delivery=promised,is_late=label,approval_hours=1,promised_days=5)
    frame=pd.DataFrame([
        row("fit0","2018-03-01","2018-03-10","2018-03-15",0),
        row("fit1","2018-03-01","2018-03-20","2018-03-15",1),
        row("fit_unknown","2018-04-20","2018-05-01","2018-04-25",1),
        row("val0","2018-05-01","2018-05-10","2018-05-15",0),
        row("val1","2018-05-01","2018-06-20","2018-06-15",1),
        row("val_unknown","2018-05-01","2018-07-01","2018-06-15",1),
        row("test","2018-07-01","2018-07-10","2018-07-15",0)])
    fit,val=ml.development_split(frame,ml.PROTOCOL['folds'][-1],min_rows=1)
    assert list(fit.order_id)==['fit0','fit1'] and list(val.order_id)==['val0','val1']
    with pytest.raises(ValueError,match='Duplicate'):
        ml.eligible(pd.concat([frame,frame.iloc[:1]]))


def test_selection_and_gate_prioritize_precision_without_latest_regression():
    summary={'baseline_logistic':dict(precision=.20,pr_auc_ap=.30),
             'baseline_hist':dict(precision=.18,pr_auc_ap=.40),
             'new':dict(precision=.23,pr_auc_ap=.29)}
    assert ml.choose_candidate(summary)=='new'
    latest={name:dict(precision=value) for name,value in [('baseline_logistic',.22),('baseline_hist',.20),('new',.21)]}
    assert not ml.promotion_gate(summary,latest,'new')['passed']
    latest['new']['precision']=.23
    assert ml.promotion_gate(summary,latest,'new')['passed']


def test_precision_threshold_cannot_win_by_catching_only_one_in_ten():
    y=np.array([1]+[0]*20+[1]*9);prob=np.linspace(.99,.01,len(y))
    threshold=ml.choose_threshold(y,prob)
    result=ml.metric(y,prob,threshold)
    assert result['recall']>=.30 and threshold<.99
    assert result['true_positives']+result['false_negatives']==10
    assert result['alerts']==result['true_positives']+result['false_positives']


def test_native_categorical_and_unseen_values_predict_without_outcome_columns():
    model,features=ml.candidate('shipping_hist_small')
    assert not set(features)&{'actual_delivery','actual_delivery_days','is_late','review_score','review_count'}
    values={name:np.ones(200) for name in ml.NUMERIC+shipping.NUMERIC}
    values.update({name:['SP']*200 for name in ml.CATEGORICAL+shipping.CATEGORICAL})
    fit=pd.DataFrame(values);other=fit.copy();other['state_route']='unseen'
    with threadpool_limits(limits=2):
        model.fit(fit[features],np.arange(200)%2)
        prediction=model.predict_proba(other[features])[:,1]
    assert np.isfinite(prediction).all()


def test_feature_cache_rejects_tampering_and_changed_order_values(tmp_path,monkeypatch):
    cache_path=tmp_path/'features.joblib';model_path=tmp_path/'model.joblib'
    row={name:1.0 for name in ml.NUMERIC};row.update({name:'SP' for name in ml.CATEGORICAL})
    frame=pd.DataFrame([row],index=['a'])
    joblib.dump({'frame':frame},cache_path)
    model=DummyClassifier(strategy='prior').fit(pd.concat([frame,frame]),[0,1])
    bundle=dict(model=model,features=ml.FEATURES,threshold=.5,name='fixture',sklearn=ml.sklearn.__version__,
                feature_cache_sha256=hashlib.sha256(cache_path.read_bytes()).hexdigest())
    joblib.dump(bundle,model_path)
    monkeypatch.setattr(ml,'MODEL',model_path);monkeypatch.setattr(ml,'FEATURE_CACHE',cache_path)
    assert ml.predict(dict(row,order_id='a'))['risk_score']==.5
    with pytest.raises(ValueError,match='Dữ liệu đơn đã đổi'):
        ml.predict(dict(row,order_id='a',product_gmv=1000))
    cache_path.write_bytes(cache_path.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='không khớp'):
        ml.predict(dict(row,order_id='a'))
