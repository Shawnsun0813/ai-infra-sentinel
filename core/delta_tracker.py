from typing import List, Dict, Tuple
from core.models import ConstraintSnapshot, DeltaResult, Country, Sector

def compute_deltas(
    today: List[ConstraintSnapshot],
    t1: List[ConstraintSnapshot],
    t7: List[ConstraintSnapshot]
) -> List[DeltaResult]:
    
    # Helper to create a lookup map
    def build_lookup(snaps: List[ConstraintSnapshot]) -> Dict[Tuple[Sector, Country], int]:
        return {(s.sector, s.country): s.severity_score for s in snaps}
        
    today_map = build_lookup(today)
    t1_map = build_lookup(t1)
    t7_map = build_lookup(t7)
    
    results = []
    
    # We compute deltas for all pairs present in today_map
    # If there are historical records for pairs missing today, they are not strictly 'current' deltas.
    # To be safe, let's collect all unique pairs across the three sets.
    all_pairs = set(today_map.keys()) | set(t1_map.keys()) | set(t7_map.keys())
    
    for sector, country in all_pairs:
        score_today = today_map.get((sector, country), 0)
        score_t1 = t1_map.get((sector, country), 0)
        score_t7 = t7_map.get((sector, country), 0)
        
        delta_1d = score_today - score_t1
        delta_7d = score_today - score_t7
        
        results.append(
            DeltaResult(
                sector=sector,
                country=country,
                score_today=score_today,
                score_t1=score_t1,
                score_t7=score_t7,
                delta_1d=delta_1d,
                delta_7d=delta_7d
            )
        )
        
    return results
