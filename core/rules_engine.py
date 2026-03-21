from typing import List, Tuple, Dict
from collections import defaultdict
from datetime import timedelta

from core.models import ConstraintSnapshot, DeltaResult, RegimeStatus, Sector, Country

def identify_bottleneck(snapshots: List[ConstraintSnapshot]) -> Sector:
    """Return sector with highest average severity across US+CN"""
    scores = defaultdict(list)
    for s in snapshots:
        scores[s.sector].append(s.severity_score)
        
    if not scores:
        return Sector.GPU_CHIPS # Arbitrary fallback if empty
        
    avg_scores = {sec: sum(vals) / len(vals) for sec, vals in scores.items()}
    return max(avg_scores.items(), key=lambda x: x[1])[0]

def evaluate_regime(
    deltas: List[DeltaResult],
    history_7d: List[ConstraintSnapshot]
) -> Tuple[RegimeStatus, Sector]:
    
    if not history_7d:
        return RegimeStatus.STABLE, Sector.GPU_CHIPS
        
    latest_date = max(s.date for s in history_7d)
    today_snaps = [s for s in history_7d if s.date == latest_date]
    bottleneck_today = identify_bottleneck(today_snaps)
    
    # Group history by (sector, country)
    history_by_sc = defaultdict(list)
    for s in history_7d:
        history_by_sc[(s.sector, s.country)].append(s)
        
    # Check Rule 1: REGIME_CHANGE
    # If any sector severity > 80 for 3+ consecutive days AND delta_1d > 15
    regime_change = False
    
    for (sec, country), snaps in history_by_sc.items():
        snaps.sort(key=lambda x: x.date, reverse=True)
        streak = 0
        
        for s in snaps:
            # Check if this snapshot extends the streak (i.e. is adjacent to the streak count)
            if s.severity_score > 80 and (latest_date - s.date).days == streak:
                streak += 1
            else:
                break
                
        if streak >= 3:
            # Check delta_1d for this specific sector and country
            delta = next((d for d in deltas if d.sector == sec and d.country == country), None)
            if delta and delta.delta_1d > 15:
                regime_change = True
                break
                
    if regime_change:
        return RegimeStatus.REGIME_CHANGE, bottleneck_today
        
    # Check Rule 2: BOTTLENECK_SHIFT
    # highest-severity sector today != highest-severity sector 7d ago
    # Compute 7d ago bottleneck using deltas where score_t7 is available
    t7_scores = defaultdict(list)
    for d in deltas:
        # Assuming missing data defaults to 0 as implemented in compute_deltas
        t7_scores[d.sector].append(d.score_t7)
        
    bottleneck_t7 = None
    if t7_scores:
        avg_t7 = {sec: sum(vals) / len(vals) for sec, vals in t7_scores.items()}
        bottleneck_t7 = max(avg_t7.items(), key=lambda x: x[1])[0]
        
    if bottleneck_t7 is not None and bottleneck_today != bottleneck_t7:
        return RegimeStatus.BOTTLENECK_SHIFT, bottleneck_today
        
    # Rule 3: STABLE if all sectors < 50
    # What if neither Rule 1, 2, or 3 strictly applies? The Prompt implies Priority, 
    # but we should return STABLE as a default fallback regime if nothing else hits.
    return RegimeStatus.STABLE, bottleneck_today
