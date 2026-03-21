import pytest
from datetime import date
from core.models import ConstraintSnapshot, Sector, Country
from core.delta_tracker import compute_deltas

def test_compute_deltas_full_data():
    today = [ConstraintSnapshot(date=date(2026, 3, 20), country=Country.US, sector=Sector.GPU_CHIPS, severity_score=80, top_signals=[], source_urls=[], reasoning="")]
    t1 = [ConstraintSnapshot(date=date(2026, 3, 19), country=Country.US, sector=Sector.GPU_CHIPS, severity_score=60, top_signals=[], source_urls=[], reasoning="")]
    t7 = [ConstraintSnapshot(date=date(2026, 3, 13), country=Country.US, sector=Sector.GPU_CHIPS, severity_score=50, top_signals=[], source_urls=[], reasoning="")]
    
    results = compute_deltas(today, t1, t7)
    assert len(results) == 1
    res = results[0]
    assert res.score_today == 80
    assert res.score_t1 == 60
    assert res.score_t7 == 50
    assert res.delta_1d == 20
    assert res.delta_7d == 30

def test_compute_deltas_missing_historical():
    today = [ConstraintSnapshot(date=date(2026, 3, 20), country=Country.US, sector=Sector.GPU_CHIPS, severity_score=75, top_signals=[], source_urls=[], reasoning="")]
    t1 = [] # Missing t1
    t7 = [] # Missing t7
    
    results = compute_deltas(today, t1, t7)
    assert len(results) == 1
    res = results[0]
    assert res.score_today == 75
    assert res.score_t1 == 0
    assert res.score_t7 == 0
    assert res.delta_1d == 75
    assert res.delta_7d == 75

def test_compute_deltas_missing_today():
    today = []
    t1 = [ConstraintSnapshot(date=date(2026, 3, 19), country=Country.CN, sector=Sector.POWER_ENERGY, severity_score=90, top_signals=[], source_urls=[], reasoning="")]
    t7 = [ConstraintSnapshot(date=date(2026, 3, 13), country=Country.CN, sector=Sector.POWER_ENERGY, severity_score=85, top_signals=[], source_urls=[], reasoning="")]
    
    results = compute_deltas(today, t1, t7)
    assert len(results) == 1
    res = results[0]
    assert res.score_today == 0
    assert res.score_t1 == 90
    assert res.score_t7 == 85
    assert res.delta_1d == -90
    assert res.delta_7d == -85
