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

EXTRACTION_PROMPT = """You are an AI infrastructure supply chain analyst.
Analyze the following raw data about the {sector} sector in {country}.

SCORING RUBRIC (follow strictly):
- 0-20: No constraints detected. Supply chain operating normally.
- 21-40: Minor delays or concerns. Lead times within normal range.
- 41-60: Moderate constraints. Some delays, capacity tightening, or policy uncertainty.
- 61-80: Significant constraints. Extended lead times, capacity shortages, or regulatory hurdles.
- 81-100: Critical bottleneck. Severe shortages, multi-year delays, or major policy disruptions.

IMPORTANT RULES:
- DO NOT default to 75. Each sector should have a DIFFERENT score based on actual evidence.
- If the raw data is mostly generic HTML with no specific constraint signals, score 30-40.
- If you find specific numbers (lead times, utilization rates, queue lengths), cite them.
- A score of 0 means you found ZERO relevant data — only use if raw text is completely empty.
- Scores should vary: a healthy sector might be 25, a constrained one 80. Not everything is 75.

Extract:
1. severity_score (0-100): Follow the rubric above
2. top_signals: Up to 3 specific data points with numbers (e.g., "PJM queue: 2,600 projects, 4.2yr avg wait")
3. reasoning: 2-3 sentences explaining WHY you gave this specific score, citing evidence from the data
4. source_urls: Any URLs found in the raw text

Respond ONLY in valid JSON matching this schema:
{schema}
"""

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
    
    # Take first 1500 chars from each source, up to 4500 total
    combined_parts = []
    for ct in cleaned_texts[:3]:
        combined_parts.append(ct[:1500])
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
