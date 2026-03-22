from dotenv import load_dotenv
load_dotenv()
import os
import asyncio
from datetime import date
from pydantic import ValidationError
from openai import AsyncOpenAI
import json
import re

from core.models import ConstraintSnapshot, Sector, Country
from core.logger import get_logger

def clean_html(text: str) -> str:
    """Strip HTML tags, scripts, styles, and excess whitespace"""
    # Remove script and style blocks entirely
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Remove HTML entities
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

logger = get_logger('engine')

EXTRACTION_PROMPT = """You are a senior AI infrastructure supply chain analyst 
at a hedge fund. You must produce a constraint severity assessment for the 
{sector} sector in {country}.

IMPORTANT: You MUST give a specific, differentiated score. Every sector has 
DIFFERENT constraint levels. Scores of exactly 30 are FORBIDDEN unless you 
can justify why this sector has zero constraints.

SCORING RUBRIC:
- 15-25: Healthy. No significant supply chain issues detected.
- 26-40: Low concern. Minor delays possible but within normal range.
- 41-55: Moderate. Noticeable constraints, some capacity tightening.
- 56-70: Elevated. Clear bottlenecks, extended lead times, supply-demand gaps.
- 71-85: Severe. Major shortages, multi-year project delays, critical capacity gaps.
- 86-100: Crisis. Systemic failure, extreme shortages, emergency conditions.

ANALYSIS APPROACH:
1. Look for ANY quantitative signals: numbers, percentages, dates, dollar amounts
2. Look for keywords: "delay", "shortage", "backlog", "queue", "lead time", "capacity"
3. Even from promotional or news content, infer the state of the sector
4. Consider what you ALREADY KNOW about this sector's current state as context
5. If the data mentions specific projects, regulations, or market conditions, USE them

For {sector} in {country}, consider these sector-specific factors:
- GPU/Chips: CoWoS packaging capacity, HBM yield rates, foundry lead times
- Data Centers: Construction timelines, zoning approvals, land costs
- Power & Energy: Grid interconnection queue length, transformer lead times, PPA pricing
- Cloud/Compute: Hyperscaler capex trends, spot GPU pricing, utilization rates
- Cooling & Infra: Liquid cooling adoption, water restrictions, equipment delivery
- Policy: Export controls, subsidy programs, regulatory changes

Output ONLY valid JSON:
{schema}

CRITICAL: If the input contains sections marked '=== VERIFIED DATA SOURCE ===' 
these are from official government APIs (EIA, FRED, Federal Register). 
Trust these numbers completely and BASE your score primarily on them.
For example:
- Electricity prices above 15 cents/kWh in major states = elevated power costs (score 55+)
- Durable goods orders declining month-over-month = weakening demand signal (score 40-50)
- Federal Register showing 20+ new regulations = active regulatory pressure (score 50+)
- PJM queue with 400+ projects = significant grid bottleneck (score 70+)

REMEMBER: Score of exactly 30 is NOT ALLOWED. Differentiate your scores."""

_client = None

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client

import openai

async def extract_constraints(
    raw_texts: list[str], sector: Sector, country: Country, scan_date: date
) -> ConstraintSnapshot:
    """Uses LLM to extract constraints from raw text."""
    valid_texts = [t for t in raw_texts if t and isinstance(t, str)]
    
    cleaned_texts = []
    for t in valid_texts:
        cleaned = clean_html(t)
        if len(cleaned) > 100:  # skip very short/empty results
            cleaned_texts.append(cleaned)
    
    if not cleaned_texts:
        return ConstraintSnapshot(
            date=scan_date,
            country=country,
            sector=sector,
            severity_score=30,
            top_signals=["Insufficient data"],
            reasoning="No substantive data available for this sector.",
            source_urls=[]
        )
    
    structured = [t for t in cleaned_texts if 'VERIFIED DATA SOURCE' in t]
    unstructured = [t for t in cleaned_texts if 'VERIFIED DATA SOURCE' not in t]
    
    combined_parts = []
    # Structured data gets 2000 chars
    for s in structured:
        combined_parts.append(s[:2000])
    # Unstructured fills remaining up to 4000 total
    remaining = 4000 - sum(len(p) for p in combined_parts)
    for u in unstructured:
        if remaining <= 0:
            break
        combined_parts.append(u[:remaining])
        remaining -= len(u[:remaining])
    
    combined_text = "\n---\n".join(combined_parts)
        
    schema_json = json.dumps(ConstraintSnapshot.model_json_schema(), indent=2)
    
    system_prompt = EXTRACTION_PROMPT.format(
        sector=sector.value,
        country=country.value,
        schema=schema_json
    )
    
    user_prompt = f"Raw Text for {sector.value} in {country.value}:\n{combined_text}"
    
    max_retries = 2
    attempt = 0
    
    while attempt <= max_retries:
        try:
            client = get_client()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0
                ),
                timeout=60.0
            )
            
            raw_json = response.choices[0].message.content
            if not raw_json:
                raise ValueError("Empty response from LLM")
                
            data = json.loads(raw_json)
            # FORCE the date to scan_date, never trust LLM's date
            data["date"] = str(scan_date)
            data["country"] = country.value
            data["sector"] = sector.value
            
            snapshot = ConstraintSnapshot.model_validate(data)
            return snapshot
            
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            attempt += 1
            if attempt > max_retries:
                logger.error(f"Failed to extract constraints for {sector.value} in {country.value}: {e}")
                raise ValueError(f"Constraint extraction failed after {max_retries} retries: {e}") from e
        except openai.RateLimitError as e:
            attempt += 1
            if attempt > max_retries:
                logger.error(f"API Rate limit giving up for {sector.value} in {country.value}: {e}")
                raise e
            await asyncio.sleep(3)  # Wait 3 seconds, retry up to 2 times
        except Exception as e:
            logger.error(f"API Error during extraction for {sector.value} in {country.value}: {e}")
            raise e

async def process_all_sectors(
    us_raw: dict[str, list[str]], cn_raw: dict[str, list[str]], scan_date: date
) -> list[ConstraintSnapshot]:
    """Processes 12 sector/country combinations concurrently with a semaphore."""
    semaphore = asyncio.Semaphore(2)
    
    async def extract_with_limit(raw, sector, country, dt):
        async with semaphore:
            result = await extract_constraints(raw, sector, country, dt)
            await asyncio.sleep(0.3)
            return result
            
    tasks = []
    for sector in Sector:
        for country_val, raw_data in [("US", us_raw), ("CN", cn_raw)]:
            country = Country(country_val)
            texts = raw_data.get(sector.value, [])
            tasks.append(extract_with_limit(texts, sector, country, scan_date))
            
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, ConstraintSnapshot)]
