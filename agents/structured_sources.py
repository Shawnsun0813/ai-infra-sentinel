import httpx
import csv
import io
import json

async def fetch_pjm_queue(client: httpx.AsyncClient) -> dict:
    '''Fetch PJM interconnection queue summary stats'''
    url = 'https://www.pjm.com/-/media/planning/services-requests/interconnection-queues.ashx'
    try:
        resp = await client.get(url, timeout=30, follow_redirects=True)
        if resp.status_code == 200:
            reader = csv.DictReader(io.StringIO(resp.text))
            rows = list(reader)
            total_projects = len(rows)
            dc_projects = [r for r in rows if 'data center' in str(r).lower() or int(float(r.get('MW', 0) or 0)) > 100]
            return {
                'total_queue_projects': total_projects,
                'data_center_projects': len(dc_projects),
                'total_mw_pending': sum(int(float(r.get('MW', 0) or 0)) for r in rows),
                'source': 'PJM Interconnection Queue (official CSV)'
            }
        return {'error': f'HTTP {resp.status_code}', 'source': 'PJM'}
    except Exception as e:
        return {'error': str(e), 'source': 'PJM'}

async def fetch_eia_grid(client: httpx.AsyncClient, api_key: str) -> dict:
    '''Fetch grid capacity and generation data from EIA'''
    url = 'https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/'
    params = {
        'api_key': api_key,
        'frequency': 'monthly',
        'data[0]': 'value',
        'sort[0][column]': 'period',
        'sort[0][direction]': 'desc',
        'length': 12
    }
    try:
        resp = await client.get(url, params=params, timeout=30)
        data = resp.json()
        return {
            'grid_generation_data': data.get('response', {}).get('data', [])[:5],
            'source': 'EIA API v2 (official)'
        }
    except Exception as e:
        return {'error': str(e), 'source': 'EIA'}

async def fetch_fred_tech_capex(client: httpx.AsyncClient, api_key: str) -> dict:
    '''Fetch semiconductor shipments and tech capex indicators'''
    series = {
        'semiconductor_shipments': 'MNFCTRSSMSA',
        'tech_equipment_orders': 'AMDMNO',
    }
    results = {}
    for name, series_id in series.items():
        url = 'https://api.stlouisfed.org/fred/series/observations'
        params = {
            'api_key': api_key, 'series_id': series_id,
            'sort_order': 'desc', 'limit': 6, 'file_type': 'json'
        }
        try:
            resp = await client.get(url, params=params, timeout=30)
            data = resp.json()
            results[name] = data.get('observations', [])[:3]
        except: pass
    results['source'] = 'FRED API (Federal Reserve)'
    return results

async def fetch_federal_register(client: httpx.AsyncClient) -> dict:
    '''Fetch recent AI/semiconductor/export control regulations'''
    url = 'https://www.federalregister.gov/api/v1/documents.json'
    params = {
        'conditions[term]': 'semiconductor OR artificial intelligence OR export control',
        'conditions[type][]': 'RULE',
        'order': 'newest',
        'per_page': 5
    }
    try:
        resp = await client.get(url, params=params, timeout=30)
        data = resp.json()
        docs = data.get('results', [])
        return {
            'recent_regulations': [{'title': d['title'], 'date': d['publication_date'],
                'agencies': [a['name'] for a in d.get('agencies',[])]} for d in docs],
            'total_count': data.get('count', 0),
            'source': 'Federal Register API (official)'
        }
    except Exception as e:
        return {'error': str(e), 'source': 'Federal Register'}

def structured_to_text(data: dict) -> str:
    '''Convert structured API data to text for LLM analysis'''
    return json.dumps(data, indent=2, default=str)
