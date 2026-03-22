from dotenv import load_dotenv
load_dotenv()
import os
import asyncio
from datetime import date
from pydantic import ValidationError
from openai import AsyncOpenAI
import json

from core.models import ConstraintSnapshot, Sector, Country
from core.logger import get_logger

logger = get_logger('engine')

EXTRACTION_PROMPT = """
You are an infrastructure supply chain analyst.
Given raw text about the {sector} sector in {country}, extract the key constraints.

Your output must be a valid JSON object matching this schema:
{schema}

Guidelines:
- severity_score: An integer from 0-100 indicating how constrained this sector is (100 = completely blocked/max constraint).
- top_signals: Max 3 key data points supporting the score (e.g., lead times, utilization %, delays).
- reasoning: 2-3 sentence explanation of the score.
- source_urls: Any URLs found in the raw text supporting the claims.

Extract ONLY valid JSON and no markdown formatting or extra text.
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
    combined_text = "\n\n---\n\n".join(valid_texts)[:2000]
        
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
            # Ensure the required kwargs are present if LLM missed them
            data["date"] = data.get("date", str(scan_date))
            data["country"] = country.value
            data["sector"] = sector.value
            
            json_str = json.dumps(data)
            snapshot = ConstraintSnapshot.model_validate_json(json_str)
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
