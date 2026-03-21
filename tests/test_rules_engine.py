import pytest
from datetime import date, timedelta
from core.models import ConstraintSnapshot, DeltaResult, Sector, Country, RegimeStatus
from core.rules_engine import evaluate_regime, identify_bottleneck

def create_snap(days_ago: int, sector: Sector, score: int, country=Country.US) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        date=date(2026, 3, 20) - timedelta(days=days_ago),
        country=country,
        sector=sector,
        severity_score=score,
        top_signals=["signal"],
        source_urls=["http://example.com"],
        reasoning="reason"
    )

def create_delta(sector: Sector, score_today: int, score_t1: int, score_t7: int, country=Country.US) -> DeltaResult:
    return DeltaResult(
        sector=sector,
        country=country,
        score_today=score_today,
        score_t1=score_t1,
        score_t7=score_t7,
        delta_1d=score_today - score_t1,
        delta_7d=score_today - score_t7,
    )

def test_identify_bottleneck():
    snaps = [
        create_snap(0, Sector.GPU_CHIPS, 80, Country.US),
        create_snap(0, Sector.GPU_CHIPS, 60, Country.CN),
        create_snap(0, Sector.POWER_ENERGY, 90, Country.US),
        create_snap(0, Sector.POWER_ENERGY, 90, Country.CN),
    ]
    assert identify_bottleneck(snaps) == Sector.POWER_ENERGY

def test_stable_all_low():
    history = [create_snap(0, Sector.GPU_CHIPS, 40), create_snap(7, Sector.GPU_CHIPS, 30)]
    deltas = [create_delta(Sector.GPU_CHIPS, 40, 35, 30)]
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.STABLE
    assert bottleneck == Sector.GPU_CHIPS

def test_stable_mixed_below_50():
    history = [
        create_snap(0, Sector.DATA_CENTERS, 49),
        create_snap(0, Sector.COOLING_INFRA, 20),
        create_snap(7, Sector.DATA_CENTERS, 49),
        create_snap(7, Sector.COOLING_INFRA, 20)
    ]
    deltas = [
        create_delta(Sector.DATA_CENTERS, 49, 45, 49),
        create_delta(Sector.COOLING_INFRA, 20, 20, 20)
    ]
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.STABLE
    assert bottleneck == Sector.DATA_CENTERS

def test_bottleneck_shift_simple():
    history = [
        create_snap(0, Sector.POWER_ENERGY, 90),
        create_snap(0, Sector.GPU_CHIPS, 50),
        create_snap(7, Sector.GPU_CHIPS, 90),
        create_snap(7, Sector.POWER_ENERGY, 50)
    ]
    deltas = [
        create_delta(Sector.POWER_ENERGY, 90, 80, 50),
        create_delta(Sector.GPU_CHIPS, 50, 60, 90)
    ]
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.BOTTLENECK_SHIFT
    assert bottleneck == Sector.POWER_ENERGY

def test_bottleneck_shift_with_cn():
    history = [
        create_snap(0, Sector.CLOUD_COMPUTE, 85, Country.CN),
        create_snap(0, Sector.POLICY, 40, Country.US),
        create_snap(7, Sector.POLICY, 85, Country.US),
        create_snap(7, Sector.CLOUD_COMPUTE, 40, Country.CN)
    ]
    deltas = [
        create_delta(Sector.CLOUD_COMPUTE, 85, 80, 40, Country.CN),
        create_delta(Sector.POLICY, 40, 50, 85, Country.US),
    ]
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.BOTTLENECK_SHIFT
    assert bottleneck == Sector.CLOUD_COMPUTE

def test_regime_change():
    # 3 consecutive days > 80, delta_1d > 15
    history = [
        create_snap(0, Sector.GPU_CHIPS, 95),
        create_snap(1, Sector.GPU_CHIPS, 90),
        create_snap(2, Sector.GPU_CHIPS, 85),
    ]
    deltas = [create_delta(Sector.GPU_CHIPS, 95, 75, 50)] # delta_1d = 20
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.REGIME_CHANGE

def test_regime_change_multiple_sectors():
    history = [
        create_snap(0, Sector.POWER_ENERGY, 95),
        create_snap(1, Sector.POWER_ENERGY, 85),
        create_snap(2, Sector.POWER_ENERGY, 82),
        create_snap(0, Sector.DATA_CENTERS, 70),
    ]
    deltas = [
        create_delta(Sector.POWER_ENERGY, 95, 75, 60), # delta_1d = 20
        create_delta(Sector.DATA_CENTERS, 70, 70, 70)
    ]
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.REGIME_CHANGE
    assert bottleneck == Sector.POWER_ENERGY

def test_regime_change_overrides_bottleneck_shift():
    # Top sector 7d ago was GPU_CHIPS
    # Top sector today is POWER_ENERGY (shift!)
    # And POWER_ENERGY meets regime change criteria (3 days > 80, delta_1d > 15)
    history = [
        create_snap(0, Sector.POWER_ENERGY, 95),
        create_snap(1, Sector.POWER_ENERGY, 85),
        create_snap(2, Sector.POWER_ENERGY, 82),
        create_snap(7, Sector.GPU_CHIPS, 90),
        create_snap(0, Sector.GPU_CHIPS, 50),
    ]
    deltas = [
        create_delta(Sector.POWER_ENERGY, 95, 75, 40), # delta_1d = 20
        create_delta(Sector.GPU_CHIPS, 50, 50, 90),    # delta_1d = 0
    ]
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.REGIME_CHANGE # Should override
    assert bottleneck == Sector.POWER_ENERGY

def test_stable_due_to_no_delta_spike():
    # 3 consecutive days > 80, but delta_1d <= 15
    history = [
        create_snap(0, Sector.GPU_CHIPS, 95),
        create_snap(1, Sector.GPU_CHIPS, 90),
        create_snap(2, Sector.GPU_CHIPS, 85),
        create_snap(7, Sector.GPU_CHIPS, 95), 
    ]
    # No shift, no > 15 delta
    deltas = [create_delta(Sector.GPU_CHIPS, 95, 90, 95)] # delta_1d = 5
    regime, bottleneck = evaluate_regime(deltas, history)
    assert regime == RegimeStatus.STABLE # Because delta_1d not > 15, and no shift
    assert bottleneck == Sector.GPU_CHIPS
