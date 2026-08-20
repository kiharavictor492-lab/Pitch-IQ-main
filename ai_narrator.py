"""
football_bot/ai_narrator.py
============================
Uses Claude (claude-sonnet-4-20250514) to generate a natural-language
match analysis narrative for the VIP channel.
"""

import requests
import logging
import json

logger = logging.getLogger(__name__)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"


def generate_narrative(pred: dict) -> str:
    """
    Given a prediction dict, ask Claude to write a 3-5 sentence
    expert analysis for the VIP channel.
    """
    home  = pred["home_team"]
    away  = pred["away_team"]
    league = pred["league"]

    context = {
        "match":        f"{home} vs {away} ({league})",
        "home_win_pct": f"{round(pred['home_win_prob']*100)}%",
        "draw_pct":     f"{round(pred['draw_prob']*100)}%",
        "away_win_pct": f"{round(pred['away_win_prob']*100)}%",
        "home_xg":      pred["home_xg"],
        "away_xg":      pred["away_xg"],
        "btts_prob":    f"{round(pred['btts_prob']*100)}%",
        "goals_over25": f"{round(pred['goals_over_25']*100)}%",
        "home_form":    "".join(pred.get("home_form", [])),
        "away_form":    "".join(pred.get("away_form", [])),
        "h2h_summary":  pred.get("h2h", {}),
        "confidence":   pred.get("confidence", 50),
        "injuries":     pred.get("injuries", [])[:3],
        "top_outcome":  pred.get("top_outcome", ""),
    }

    prompt = f"""You are a professional football analyst writing for a sports betting VIP channel.

Here is the statistical data for an upcoming match:
{json.dumps(context, indent=2)}

Write a concise, expert analysis (3-5 sentences) covering:
1. The likely match dynamic and key factor influencing the outcome
2. Why the statistical model favours the top outcome
3. Any relevant form/H2H insight
4. A brief mention of goal expectation

Be confident but acknowledge uncertainty. Write in plain English, no bullet points.
Keep it under 120 words. Do NOT include odds or suggest specific bets explicitly."""

    try:
        response = requests.post(
            CLAUDE_API_URL,
            headers={"Content-Type": "application/json"},
            json={
                "model":      MODEL,
                "max_tokens": 250,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        return text.strip()
    except Exception as e:
        logger.error(f"Claude API error for narrative: {e}")
        return (
            f"{home} and {away} meet in what the numbers suggest will be a "
            f"{'high-scoring' if pred['goals_over_25'] > 0.6 else 'tight'} affair. "
            f"Our model gives {pred['top_outcome']} as the most likely result at "
            f"{round(pred['top_prob']*100)}% probability."
        )
