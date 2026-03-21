from datetime import date
from enum import Enum
from typing import List, Literal

from pydantic import BaseModel, Field


class Country(str, Enum):
    US = "US"
    CN = "CN"


class Sector(str, Enum):
    GPU_CHIPS = "GPU_CHIPS"
    DATA_CENTERS = "DATA_CENTERS"
    POWER_ENERGY = "POWER_ENERGY"
    CLOUD_COMPUTE = "CLOUD_COMPUTE"
    COOLING_INFRA = "COOLING_INFRA"
    POLICY = "POLICY"


class ConstraintSnapshot(BaseModel):
    date: date
    country: Country
    sector: Sector
    severity_score: int = Field(ge=0, le=100)
    top_signals: List[str] = Field(max_length=3)
    source_urls: List[str]
    reasoning: str


class DeltaResult(BaseModel):
    sector: Sector
    country: Country
    score_today: int
    score_t1: int
    score_t7: int
    delta_1d: int
    delta_7d: int


class RegimeStatus(str, Enum):
    STABLE = "STABLE"
    BOTTLENECK_SHIFT = "BOTTLENECK_SHIFT"
    REGIME_CHANGE = "REGIME_CHANGE"


class TradeIdea(BaseModel):
    direction: Literal["LONG", "SHORT"]
    ticker: str
    rationale: str
    conviction: Literal["HIGH", "MED", "LOW"]
    horizon: str


class DailyScanResult(BaseModel):
    date: date
    regime: RegimeStatus
    current_bottleneck: Sector
    snapshots: List[ConstraintSnapshot]
    deltas: List[DeltaResult]
    trade_ideas: List[TradeIdea]
    synthesis_bullets: List[str]
