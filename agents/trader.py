import os
import json
from openai import AsyncOpenAI
from core.models import RegimeStatus, Sector, DeltaResult, ConstraintSnapshot, TradeIdea

_client = None

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client

TRADER_PROMPT = """
You are a quantitative macro trader. 
Analyze the current macro regime, bottleneck sector, deltas, and constraint snapshots.
Provide 3-5 thematic trade ideas that profit from these constraints and shifts.
Each trade idea must have: direction (LONG or SHORT), ticker, rationale, conviction (HIGH, MED, or LOW), and horizon.

Output MUST be a JSON object containing a list of trade ideas under the key "ideas", matching this structure:
{
  "ideas": [
    {
      "direction": "LONG",
      "ticker": "NVDA",
      "rationale": "...",
      "conviction": "HIGH",
      "horizon": "3-6 months"
    }
  ]
}
"""

async def generate_trade_ideas(
    regime: RegimeStatus, bottleneck: Sector,
    deltas: list[DeltaResult], snapshots: list[ConstraintSnapshot]
) -> list[TradeIdea]:
    """Generates thematic trade ideas in JSON responding to the macro environment."""
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
                {"role": "system", "content": TRADER_PROMPT},
                {"role": "user", "content": json.dumps(context, indent=2)}
            ],
            response_format={"type": "json_object"},
            temperature=0.5
        )
        
        raw_output = response.choices[0].message.content
        if not raw_output:
            raise ValueError("Empty response from LLM")
            
        data = json.loads(raw_output)
        ideas_raw = data.get("ideas", [])
        
        ideas = []
        for idea_raw in ideas_raw:
            try:
                idea = TradeIdea.model_validate(idea_raw)
                ideas.append(idea)
            except Exception as e:
                print(f"Skipping invalid trade idea: {idea_raw} due to {e}")
                
        conviction_weight = {"HIGH": 3, "MED": 2, "LOW": 1}
        ideas.sort(key=lambda x: conviction_weight.get(x.conviction, 0), reverse=True)
        
        return ideas[:5]
        
    except Exception as e:
        print(f"Error generating trade ideas: {e}")
        return []
