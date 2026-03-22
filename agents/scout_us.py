import httpx
import asyncio
import yaml
import os
from pathlib import Path
from core.models import Sector
from core.logger import get_logger

logger = get_logger('scout.us')
from agents.structured_sources import (
    fetch_pjm_queue,
    fetch_eia_grid,
    fetch_fred_tech_capex,
    fetch_federal_register,
    structured_to_text
)

# Load sources from data/sources.yaml at module level
SOURCES_FILE = Path(__file__).parent.parent / "data" / "sources.yaml"
with open(SOURCES_FILE, "r", encoding="utf-8") as f:
    SOURCES_CONFIG = yaml.safe_load(f)

US_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

async def fetch_source(client: httpx.AsyncClient, source: dict) -> str | None:
    """Fetch a single source URL with a 30s timeout."""
    url = source.get("url")
    name = source.get("name")
    if not url:
        return None
        
    for attempt in range(3):
        try:
            response = await client.get(
                url, 
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/json",
                    "Accept-Encoding": "identity"  # Disable compression to avoid binary
                }
            )
            response.raise_for_status()
            logger.info(f"Successfully fetched {name} ({response.status_code})")
            try:
                return response.text
            except Exception:
                return response.content.decode('utf-8', errors='ignore')
        except (ConnectionResetError, httpx.RemoteProtocolError) as e:
            if attempt < 2:
                await asyncio.sleep(2)
                continue
            logger.error(f"Failed after 3 retries: {name}: {e}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"Error fetching {name}: {type(e).__name__} - {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {name}: {type(e).__name__} - {e}")
            return None

async def scan_sector(sector: str, sources: list[dict]) -> list[str]:
    """Parallel fetch all sources for one sector."""
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        tasks = [fetch_source(client, src) for src in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Exception during gather: {r}")
            elif r is not None:
                valid_results.append(r)
                
        return valid_results

async def run_us_scout() -> dict[str, list[str]]:
    """Scan all 6 US sectors concurrently."""
    sectors_config = SOURCES_CONFIG.get("sectors", {})
    
    sector_tasks = {}
    for sector_name, country_data in sectors_config.items():
        us_sources = country_data.get("US", [])
        if us_sources:
            sector_tasks[sector_name] = scan_sector(sector_name, us_sources)
            
    # Run all HTML sectors concurrently
    sector_names = list(sector_tasks.keys())
    tasks = list(sector_tasks.values())
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    html_results = {}
    for name, result in zip(sector_names, results):
        if isinstance(result, Exception):
            logger.error(f"Sector {name} failed entirely: {result}")
            html_results[name] = []
        else:
            html_results[name] = result
            
    eia_key = os.getenv("EIA_API_KEY", "")
    fred_key = os.getenv("FRED_API_KEY", "")
    
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        # New structured API results
        structured = {}
        structured['POWER_ENERGY'] = await fetch_pjm_queue(client)
        structured['POWER_ENERGY_EIA'] = await fetch_eia_grid(client, eia_key)
        structured['CLOUD_COMPUTE'] = await fetch_fred_tech_capex(client, fred_key)
        structured['POLICY'] = await fetch_federal_register(client)

        import json
        # Merge: prepend structured data text to each sector's raw texts
        for sector, data in structured.items():
            sector_key = sector.split('_EIA')[0]  # normalize key
            text = f'[STRUCTURED DATA SOURCE]\n{json.dumps(data, indent=2, default=str)}'
            if sector_key in html_results:
                html_results[sector_key].insert(0, text)  # priority: structured first
            else:
                html_results[sector_key] = [text]
                
    return html_results
