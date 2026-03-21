import json
import os
from datetime import date
from typing import List, Dict, Tuple
import psycopg
from psycopg.rows import dict_row
from core.models import ConstraintSnapshot, Country, Sector

# Connection config from environment variables
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://sentinel:sentinel@localhost:5432/sentinel')

def get_conn():
    """Returns a psycopg connection using context manager."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS constraint_snapshots (
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL,
                    country TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    severity_score INTEGER NOT NULL CHECK (severity_score BETWEEN 0 AND 100),
                    top_signals JSONB NOT NULL DEFAULT '[]',
                    source_urls JSONB NOT NULL DEFAULT '[]',
                    reasoning TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (date, country, sector)
                )
            ''')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_snapshots_date ON constraint_snapshots(date)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_snapshots_sector ON constraint_snapshots(sector, country)')
        conn.commit()

def save_snapshots(snapshots: list[ConstraintSnapshot]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Use executemany with INSERT ... ON CONFLICT for upsert
            cur.executemany('''
                INSERT INTO constraint_snapshots (date, country, sector, severity_score,
                    top_signals, source_urls, reasoning)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (date, country, sector) DO UPDATE SET
                    severity_score = EXCLUDED.severity_score,
                    top_signals = EXCLUDED.top_signals,
                    source_urls = EXCLUDED.source_urls,
                    reasoning = EXCLUDED.reasoning,
                    created_at = NOW()
            ''', [(s.date, s.country.value, s.sector.value, s.severity_score,
                   json.dumps(s.top_signals), json.dumps(s.source_urls), s.reasoning)
                  for s in snapshots])
        conn.commit()

def get_snapshots_by_date(target_date: date) -> list[ConstraintSnapshot]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT * FROM constraint_snapshots WHERE date = %s', (target_date,)
            )
            rows = cur.fetchall()
            return [_row_to_snapshot(row) for row in rows]

def get_history(days: int = 7) -> list[ConstraintSnapshot]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT * FROM constraint_snapshots
                WHERE date >= CURRENT_DATE - %s::integer
                ORDER BY date DESC, sector, country
            ''', (days,))
            rows = cur.fetchall()
            return [_row_to_snapshot(row) for row in rows]

def get_latest_by_sector() -> dict[tuple[str,str], ConstraintSnapshot]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT DISTINCT ON (country, sector) *
                FROM constraint_snapshots
                ORDER BY country, sector, date DESC
            ''')
            rows = cur.fetchall()
            return {(row['country'], row['sector']): _row_to_snapshot(row) for row in rows}

def _row_to_snapshot(row: dict) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        date=row["date"],
        country=Country(row["country"]),
        sector=Sector(row["sector"]),
        severity_score=row["severity_score"],
        top_signals=row["top_signals"] if isinstance(row["top_signals"], list) else json.loads(row["top_signals"]),
        source_urls=row["source_urls"] if isinstance(row["source_urls"], list) else json.loads(row["source_urls"]),
        reasoning=row["reasoning"]
    )

def save_daily_summary(scan_date, regime, bottleneck, synthesis_bullets, trade_ideas):
    import json
    conn = get_conn()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS daily_summaries (
            id SERIAL PRIMARY KEY,
            date DATE UNIQUE NOT NULL,
            regime TEXT NOT NULL,
            bottleneck_sector TEXT NOT NULL,
            synthesis JSONB NOT NULL DEFAULT '[]',
            trade_ideas JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    conn.execute('''
        INSERT INTO daily_summaries (date, regime, bottleneck_sector, synthesis, trade_ideas)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        ON CONFLICT (date) DO UPDATE SET
            regime = EXCLUDED.regime,
            bottleneck_sector = EXCLUDED.bottleneck_sector,
            synthesis = EXCLUDED.synthesis,
            trade_ideas = EXCLUDED.trade_ideas,
            created_at = NOW()
    ''', (scan_date, regime, bottleneck, json.dumps(synthesis_bullets),
          json.dumps([t if isinstance(t, dict) else t.model_dump() for t in trade_ideas])))
    conn.commit()
    conn.close()
