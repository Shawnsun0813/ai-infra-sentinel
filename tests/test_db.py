import os
import pytest
from datetime import date, timedelta
from core.models import ConstraintSnapshot, Country, Sector
from data.db import (
    init_db, save_snapshots, get_snapshots_by_date, 
    get_history, get_latest_by_sector
)
import psycopg

# Use test database URL
original_url = os.getenv('DATABASE_URL', 'postgresql://sentinel:sentinel@localhost:5432/postgres')
os.environ['DATABASE_URL'] = os.getenv('TEST_DATABASE_URL', 'postgresql://sentinel:sentinel@localhost:5432/sentinel_test')

@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    # 1. Creates a test database
    target_db = 'sentinel_test'
    try:
        conn = psycopg.connect(original_url, autocommit=True)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        exists = cur.fetchone()
        if not exists:
            cur.execute(f"CREATE DATABASE {target_db}")
        conn.close()
    except Exception as e:
        print(f"Warning: Could not create test DB {target_db}: {e}")

@pytest.fixture(autouse=True)
def db_setup(setup_test_db):
    # 2. Initialize tables via init_db()
    init_db()
    
    # 3. Yields
    yield
    
    # 4. Drops all tables in teardown
    conn = psycopg.connect(os.environ['DATABASE_URL'], autocommit=True)
    conn.execute('DROP TABLE IF EXISTS constraint_snapshots CASCADE')
    conn.execute('DROP TABLE IF EXISTS daily_summaries CASCADE')
    conn.close()

def test_init_creates_tables():
    conn = psycopg.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    cur.execute('''
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'constraint_snapshots'
        );
    ''')
    exists = cur.fetchone()[0]
    conn.close()
    assert exists is True

def test_save_and_retrieve_snapshots():
    snapshot = ConstraintSnapshot(
        date=date(2023, 1, 1),
        country=Country.US,
        sector=Sector.GPU_CHIPS,
        severity_score=85,
        top_signals=["Signal 1"],
        source_urls=["http://example.com"],
        reasoning="Test reasoning"
    )
    save_snapshots([snapshot])
    
    retrieved = get_snapshots_by_date(date(2023, 1, 1))
    assert len(retrieved) == 1
    assert retrieved[0].severity_score == 85
    assert retrieved[0].country == Country.US
    assert retrieved[0].sector == Sector.GPU_CHIPS

def test_get_history_returns_correct_days():
    # Insert old and new snapshots
    today = date.today()
    snapshots = [
        ConstraintSnapshot(
            date=today,
            country=Country.US,
            sector=Sector.GPU_CHIPS,
            severity_score=50,
            top_signals=[],
            source_urls=[],
            reasoning="Today"
        ),
        ConstraintSnapshot(
            date=today - timedelta(days=10),
            country=Country.CN,
            sector=Sector.DATA_CENTERS,
            severity_score=60,
            top_signals=[],
            source_urls=[],
            reasoning="Old"
        )
    ]
    save_snapshots(snapshots)
    
    history = get_history(days=7)
    assert len(history) == 1
    assert history[0].date == today

def test_get_latest_by_sector():
    snapshots = [
        ConstraintSnapshot(
            date=date(2023, 1, 1),
            country=Country.US,
            sector=Sector.GPU_CHIPS,
            severity_score=50,
            top_signals=[],
            source_urls=[],
            reasoning="Old"
        ),
        ConstraintSnapshot(
            date=date(2023, 1, 2),
            country=Country.US,
            sector=Sector.GPU_CHIPS,
            severity_score=90,
            top_signals=[],
            source_urls=[],
            reasoning="New"
        )
    ]
    save_snapshots(snapshots)
    
    latest = get_latest_by_sector()
    assert ("US", "GPU_CHIPS") in latest
    assert latest[("US", "GPU_CHIPS")].severity_score == 90

def test_upsert_on_duplicate():
    snapshot1 = ConstraintSnapshot(
        date=date(2023, 1, 1),
        country=Country.US,
        sector=Sector.GPU_CHIPS,
        severity_score=50,
        top_signals=[],
        source_urls=[],
        reasoning="Initial"
    )
    save_snapshots([snapshot1])
    
    snapshot2 = ConstraintSnapshot(
        date=date(2023, 1, 1),
        country=Country.US,
        sector=Sector.GPU_CHIPS,
        severity_score=95,
        top_signals=["Updated"],
        source_urls=[],
        reasoning="Updated"
    )
    save_snapshots([snapshot2])
    
    retrieved = get_snapshots_by_date(date(2023, 1, 1))
    assert len(retrieved) == 1
    assert retrieved[0].severity_score == 95
    assert retrieved[0].top_signals == ["Updated"]

def test_severity_score_constraint():
    import psycopg.errors
    with pytest.raises(psycopg.errors.CheckViolation):
        conn = psycopg.connect(os.environ['DATABASE_URL'], autocommit=True)
        conn.execute('''
            INSERT INTO constraint_snapshots 
            (date, country, sector, severity_score, top_signals, source_urls, reasoning)
            VALUES ('2023-01-01', 'US', 'GPU_CHIPS', 150, '[]', '[]', 'Invalid')
        ''')
        conn.close()
