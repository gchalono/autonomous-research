import pytest
from evaluation_v17a.statistical import bootstrap,paired,stratified

def test_constant_tasks_ci_exact():
    r=bootstrap({'a':1,'b':1,'c':1});assert r['mean']==1 and r['interval']==[1,1] and r['n']==3

def test_hand_two_task_bootstrap():
    r=bootstrap({'a':0,'b':1},replicates=10000);assert r['mean']==.5 and r['interval']==[0,1]

def test_deterministic_seed_and_task_order():
    assert bootstrap({'a':.2,'b':.9,'c':.6})==bootstrap({'c':.6,'b':.9,'a':.2})

def test_paired_constant_difference():
    r=paired({'a':.1,'b':.5,'missing':None},{'a':.3,'b':.7,'new':1})
    assert r['mean_difference']==pytest.approx(.2);assert r['interval']==pytest.approx([.2,.2]);assert r['excluded_ids']==['missing','new']

def test_task_missingness_and_strata():
    r=bootstrap({'a':None,'b':.3});assert r['n']==1 and r['interval'] is None and r['missing']==['a']
    s=stratified({'a':0,'b':1},{'a':'factual','b':'numeric'});assert s['numeric']['mean']==1

def test_empty_no_plausible_score():
    assert bootstrap({})['mean'] is None;assert paired({},{})['mean_difference'] is None

@pytest.mark.parametrize('data',[{'a':float('nan')},{'a':float('inf')},{'a':1.1},{'a':True},{'a':'0.2'}])
def test_bad_statistics_input(data):
    with pytest.raises(ValueError):bootstrap(data)
@pytest.mark.parametrize('kwargs',[{'replicates':0},{'confidence':1},{'seed':True}])
def test_bad_statistics_configuration(kwargs):
    with pytest.raises(ValueError):bootstrap({'a':1,'b':0},**kwargs)
