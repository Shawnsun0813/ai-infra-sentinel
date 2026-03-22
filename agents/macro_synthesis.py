import os
import json
from openai import AsyncOpenAI
from core.models import RegimeStatus, Sector, DeltaResult, ConstraintSnapshot

_client = None

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client

MACRO_PROMPT = """
You are a senior macro strategist.
Analyze the following regime status, bottleneck sector, current constraints, and 7-day deltas.
Generate 3-5 bullet points synthesizing the macro situation.
Write ALL output in English only. Do NOT include any Chinese translations, pinyin, or parenthetical translations. Use clean sector names like 'GPU/Chips', 'Data Centers', 'Power & Energy', 'Cloud/Compute', 'Cooling & Infra', 'Policy' — not the enum values like 'GPU_CHIPS' or 'COOLING_INFRA'.
Output ONLY a JSON array of strings. No markdown formatting outside of the JSON array.
"""

async def generate_synthesis(
    regime: RegimeStatus, bottleneck: Sector,
    deltas: list[DeltaResult], snapshots: list[ConstraintSnapshot]
) -> list[str]:
    """Generates a macro synthesis based on current metrics."""
    context = {
        "regime": regime.value if regime else None,
        "bottleneck": bottleneck.value if bottleneck else None,
        "deltas": [d.model_dump(mode="json") for d in deltas] if deltas else [],
        "snapshots": [s.model_dump(mode="json") for s in snapshots] if snapshots else []
    }
    
    try:
        client = get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": MACRO_PROMPT},
                {"role": "user", "content": json.dumps(context, indent=2)}
            ],
            temperature=0.4
        )
        
        raw_output = response.choices[0].message.content
        if not raw_output:
            raise ValueError("Empty response from LLM")
            
        if raw_output.startswith("```json"):
            raw_output = raw_output.strip()[7:-3]
        elif raw_output.startswith("```"):
            raw_output = raw_output.strip()[3:-3]
            
        parsed = json.loads(raw_output)
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON array of strings")
        if not all(isinstance(x, str) for x in parsed):
            raise ValueError("All elements in the array must be strings")
            
        return parsed
        
    except json.JSONDecodeError as e:
        print(f"Failed to parse LLM output as JSON: {e}")
        return [f"Synthesis unavailable: JSON decode error - {e}"]
    except Exception as e:
        print(f"Error generating macro synthesis: {e}")
        return [f"Synthesis unavailable due to error: {e}"]
