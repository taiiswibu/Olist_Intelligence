import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from olist.ml import (NUMERIC, CATEGORICAL, chronological_split, choose_candidate,
                      choose_threshold, fit_and_select, metric)


def test_chronological_split_enforces_label_availability_and_disjoint_orders():
    def row(order, approval, actual, promised, **values):
        return dict(order_id=order, approved_at=approval, actual_delivery=actual,
                    estimated_delivery=promised, is_late=0, approval_hours=1, promised_days=5, **values)
    frame = pd.DataFrame([
        row("fit", "2018-02-01", "2018-02-10", "2018-02-15"),
        row("fit_outcome_not_known", "2018-02-20", "2018-03-01", "2018-02-28"),
        row("cal", "2018-03-01", "2018-03-10", "2018-03-15"),
        row("cal_promise_not_known", "2018-04-20", "2018-04-25", "2018-05-01"),
        row("val", "2018-05-01", "2018-06-20", "2018-06-25"),
        row("val_outcome_not_known", "2018-05-20", "2018-07-01", "2018-06-25"),
        row("embargo", "2018-06-01", "2018-06-10", "2018-06-15"),
        row("test", "2018-07-01", "2018-08-05", "2018-07-25"),
        row("after_test", "2018-08-01", "2018-08-10", "2018-08-15"),
    ])
    parts = chronological_split(frame)
    assert {name: list(part.order_id) for name, part in parts.items()} == {
        "fit": ["fit"], "calibration": ["cal"], "validation": ["val"], "test": ["test"]}
    with pytest.raises(ValueError, match="Duplicate order_id"):
        chronological_split(pd.concat([frame, frame.iloc[:1]]))


def test_selection_uses_validation_ap_and_brier_only_for_ap_ties():
    assert choose_candidate({"higher_ap": {"pr_auc_ap": .2, "brier": .5},
                             "lower_ap": {"pr_auc_ap": .1, "brier": .01}}) == "higher_ap"
    assert choose_candidate({"raw": {"pr_auc_ap": .2, "brier": .1},
                             "calibrated": {"pr_auc_ap": .2 + 1e-15, "brier": .05}}) == "calibrated"


def test_threshold_ties_prefer_fewer_alerts_and_confusion_counts_are_explicit():
    assert choose_threshold(np.array([0, 0, 1, 1]), np.array([.1, .2, .8, .9])) == .8
    assert choose_threshold(np.array([0, 0, 1, 1]), np.full(4, .2)) == .2
    result = metric(np.array([0, 1, 1, 0]), np.array([.9, .8, .2, .1]), .5)
    assert [result[k] for k in ("true_positives", "false_positives", "false_negatives", "true_negatives")] == [1, 1, 1, 1]
    assert result["alerts"] == 2 and result["alert_rate"] == .5


def test_calibration_does_not_refit_base_preprocessing_on_later_data():
    # Synthetic fixtures stay in tests. Large shifts expose any accidental refit.
    def frame(value, state):
        values = {name: np.full(200, value) for name in NUMERIC}
        values.update({name: [state] * 200 for name in CATEGORICAL})
        values["is_late"] = np.arange(200) % 2
        return pd.DataFrame(values)
    with threadpool_limits(limits=2):
        candidates, winner, validation = fit_and_select(frame(1, "SP"), frame(100, "RJ"), frame(200, "MG"))
    for name in ("logistic", "hist_gradient_boosting"):
        prep = candidates[name].named_steps["columntransformer"]
        numeric = prep.named_transformers_["num"]
        imputer = numeric.named_steps["simpleimputer"] if hasattr(numeric, "named_steps") else numeric
        np.testing.assert_array_equal(imputer.statistics_, np.ones(len(NUMERIC)))
        frozen = candidates[name + "_sigmoid"].calibrated_classifiers_[0].estimator
        assert frozen.estimator is candidates[name]
    assert winner in candidates and set(validation) == set(candidates)
    assert all(0 < result["threshold"] < 1 for result in validation.values())
