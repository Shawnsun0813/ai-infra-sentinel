import httpx
import asyncio
import yaml
from pathlib import Path
from core.models import Sector
from core.logger import get_logger

logger = get_logger('scout.cn')

# CN sources often need WeChat-compatible UA or proxy — TODO
CN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

SOURCES_FILE = Path(__file__).parent.parent / "data" / "sources.yaml"
with open(SOURCES_FILE, "r", encoding="utf-8") as f:
    SOURCES_CONFIG = yaml.safe_load(f)

async def fetch_source(client: httpx.AsyncClient, source: dict) -> str | None:
    """Fetch URL with 30s timeout using CN specific headers."""
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

async def run_cn_scout() -> dict[str, list[str]]:
    """Scan all 6 CN sectors concurrently."""
    sectors_config = SOURCES_CONFIG.get("sectors", {})
    
    sector_tasks = {}
    for sector_name, country_data in sectors_config.items():
        cn_sources = country_data.get("CN", [])
        if cn_sources:
            sector_tasks[sector_name] = scan_sector(sector_name, cn_sources)
            
    # Run all sectors concurrently
    sector_names = list(sector_tasks.keys())
    tasks = list(sector_tasks.values())
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    final_output = {}
    for name, result in zip(sector_names, results):
        if isinstance(result, Exception):
            logger.error(f"Sector {name} failed entirely: {result}")
            final_output[name] = []
        else:
            final_output[name] = result
            
    return final_output
