from copy import deepcopy
import pytest
from scripts.analyze_pilot import analyze


def row(**changes):
    return dict(participant_code='P001', specialization='backend', requested_grade='junior',
                score='75', expert_grade='junior', parallel_score='70', minutes='20',
                form_version='scenarios-v5', **changes) if not changes else {**row(), **changes}


def test_empty_template_never_fabricates_pilot():
    report=analyze([])
    assert report['status']=='not-conducted' and report['observations']==0 and report['groups']==[]


def test_descriptive_denominators_missing_values_and_boundaries():
    records=[row(score='70'), row(participant_code='P002', score='69', expert_grade='junior', parallel_score='', minutes=''),
             row(participant_code='P003', score='100', expert_grade='', parallel_score='80', minutes='40'),
             row(participant_code='P004', requested_grade='middle', score='79', expert_grade='unconfirmed', parallel_score='80')]
    original=deepcopy(records)
    result=analyze(records)
    junior,middle=result['groups']
    assert junior['expert_observations']==2 and junior['missing_expert']==1 and junior['category_agreement']==0.5
    assert junior['confusion_expert_rows_test_columns']['junior']==dict(unconfirmed=1,junior=1,middle=0)
    assert junior['parallel_observations']==2 and junior['mean_absolute_score_difference']==10
    assert junior['timed_observations']==2 and junior['mean_minutes']==30
    assert middle['category_agreement']==1 and records==original


@pytest.mark.parametrize('patch',[{'participant_code':'person@example.invalid'}, {'score':'nan'}, {'parallel_score':'inf'},
    {'minutes':'-1'}, {'expert_grade':'senior'}, {'form_version':'https://private'}, {'specialization':'ml'}])
def test_invalid_data_rejected(patch):
    with pytest.raises(ValueError): analyze([row(**patch)])


def test_duplicate_observation_rejected_but_separate_group_allowed():
    with pytest.raises(ValueError): analyze([row(),row()])
    assert analyze([row(),row(requested_grade='middle')])['observations']==2
