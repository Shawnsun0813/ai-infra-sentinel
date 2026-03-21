from dotenv import load_dotenv
load_dotenv()

import sys
import asyncio
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, 
                        message=".*WindowsSelectorEventLoopPolicy.*")
warnings.filterwarnings("ignore", category=DeprecationWarning,
                        message=".*set_event_loop_policy.*")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, timedelta

from core.models import DailyScanResult
from core.rules_engine import evaluate_regime, identify_bottleneck
from core.delta_tracker import compute_deltas
from data.db import init_db, save_snapshots, get_snapshots_by_date, get_history
from agents.scout_us import run_us_scout
from agents.scout_cn import run_cn_scout
from agents.constraint_engine import process_all_sectors
from agents.macro_synthesis import generate_synthesis
from agents.trader import generate_trade_ideas

async def daily_scan() -> DailyScanResult:
    """
    Executes the daily AI structural constraints scan.
    Gathers intelligence from US and CN scouts, computes regime and bottlenecks,
    and returns a summarized synthesis and trade ideas.
    """
    # Step 1: Initialize DB
    init_db()

    # Step 2: Scout US and CN concurrently
    # Global rule: Always use asyncio.gather with return_exceptions=True
    scout_results = await asyncio.gather(
        run_us_scout(),
        run_cn_scout(),
        return_exceptions=True
    )
    
    us_raw = scout_results[0] if not isinstance(scout_results[0], Exception) else []
    cn_raw = scout_results[1] if not isinstance(scout_results[1], Exception) else []

    # Step 3: Process all sectors to produce unified snapshots
    snapshots = await process_all_sectors(us_raw, cn_raw, date.today())

    # Step 4: Save snapshots to DB
    save_snapshots(snapshots)

    # Step 5: Get T-1 and T-7 snapshots
    try:
        t1 = get_snapshots_by_date(date.today() - timedelta(days=1))
    except Exception:
        t1 = []
        
    try:
        t7 = get_snapshots_by_date(date.today() - timedelta(days=7))
    except Exception:
        t7 = []

    # Step 6: Compute deltas across timeframes
    deltas = compute_deltas(snapshots, t1, t7)

    # Step 7: Get week history and evaluate regime constraints
    history = get_history(days=7)
    regime, bottleneck = evaluate_regime(deltas, history)

    # Step 8: Generate synthesis layer insights
    # Step 9: Generate trade ideas based on current regime
    downstream_results = await asyncio.gather(
        generate_synthesis(regime, bottleneck, deltas, snapshots),
        generate_trade_ideas(regime, bottleneck, deltas, snapshots),
        return_exceptions=True
    )
    
    synthesis = downstream_results[0] if not isinstance(downstream_results[0], Exception) else []
    trades = downstream_results[1] if not isinstance(downstream_results[1], Exception) else []

    # Step 10: Save daily summary & Return aggregated result
    from data.db import save_daily_summary
    save_daily_summary(
        date.today(),
        regime.value,
        bottleneck.value,
        synthesis,
        trades
    )

    return DailyScanResult(
        date=date.today(),
        regime=regime,
        current_bottleneck=bottleneck,
        snapshots=snapshots,
        deltas=deltas,
        trade_ideas=trades,
        synthesis_bullets=synthesis
    )

def main() -> None:
    """Entry point for the daily orchestration."""
    result = asyncio.run(daily_scan())
    print(f'Regime: {result.regime}')
    print(f'Bottleneck: {result.current_bottleneck}')
    for b in result.synthesis_bullets:
        print(f'  - {b}')

if __name__ == '__main__':
    main()
