"""Validate the static search model against recorded native PSCAD results."""

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('scipy')
MODULE = Path(__file__).parents[1] / 'scripts' / 'arrester_ratio_search.py'


@pytest.fixture
def search_module(monkeypatch):
    spec = importlib.util.spec_from_file_location('arrester_ratio_search_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def network(search_module):
    return search_module.StaticNetwork(
        current_ka=np.array([0, 1e-6, 1e-5, 1e-4, .001, .01, .1, .5, 1, 2, 5, 10]),
        voltage_pu=np.array([0, .5, .55, .6, .65, .75, .88, .96, 1, 1.04, 1.10, 1.16]),
        source_kv=120, source_ohm=20, on_ohm=.005, off_ohm=1e9,
    )


def test_prediction_matches_native_pscad_stage_two(network):
    result = network.stage([100, 90, 80, 70, 60], 2)
    assert result['bus_kv'] == pytest.approx(90.798761662154, abs=1e-7)
    assert result['currents_ka'][:2] == pytest.approx([.2398781135793, 1.220183540126], abs=1e-8)
    assert result['new_share'] == pytest.approx(.83570670942607, abs=1e-8)


def test_prediction_matches_native_pscad_final_distribution(network):
    result = network.stage([100, 90, 80, 70, 60], 5)
    assert result['currents_ka'] == pytest.approx(
        [.000662163396848, .00562310517778, .037025512972761, .208720692131826, 2.59181186166474],
        abs=1e-8,
    )
    assert result['bus_kv'] == pytest.approx(63.123133293306, abs=1e-7)


def test_kcl_and_equal_device_sharing(network):
    result = network.stage([80, 80, 80, 80, 80], 5)
    assert result['new_share'] == pytest.approx(.2, abs=1e-12)
    assert sum(result['currents_ka']) == pytest.approx((120 - result['bus_kv']) / 20, abs=1e-10)


def test_invalid_voltage_scale_is_rejected(network):
    with pytest.raises(ValueError, match='positive'):
        network.stage([100, 90, 0, 70, 60], 3)


def test_objective_scores_the_worst_later_stage(network):
    assert network.score([100, 90, 80, 70, 60]) == pytest.approx(.83570670942607, abs=1e-8)


@pytest.fixture
def study_module(monkeypatch):
    monkeypatch.syspath_prepend(str(MODULE.parent))
    spec = importlib.util.spec_from_file_location('arrester_ratio_study_test', MODULE.parent / 'run_arrester_ratio_study.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_changed_search_code_is_rejected(study_module, tmp_path):
    plan = {'status': 'SEARCHED_NOT_NATIVE_VERIFIED', 'search_code_sha256': 'older code'}
    with pytest.raises(RuntimeError, match='Search code'):
        study_module.verify_plan(tmp_path, plan)


def test_changed_candidate_is_rejected(study_module, tmp_path):
    models = tmp_path / 'models'
    models.mkdir()
    (models / 'ratio_baseline.pscx').write_text('modified candidate', encoding='utf-8')
    plan = {'status': 'SEARCHED_NOT_NATIVE_VERIFIED',
            'search_code_sha256': study_module.lifecycle.sha(Path(study_module.search_model.__file__)),
            'source_hashes': {}, 'search': {'candidates': {'ratio_baseline': {'model_sha256': 'old'}}}}
    with pytest.raises(RuntimeError, match='Candidate model'):
        study_module.verify_plan(tmp_path, plan)
