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
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON constraint_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_snapshots_sector ON constraint_snapshots(sector, country);

CREATE TABLE IF NOT EXISTS daily_summaries (
  id SERIAL PRIMARY KEY,
  date DATE UNIQUE NOT NULL,
  regime TEXT NOT NULL,
  bottleneck_sector TEXT NOT NULL,
  synthesis JSONB NOT NULL DEFAULT '[]',
  trade_ideas JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
