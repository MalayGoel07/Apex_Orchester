import re
import os
import logging
from google import generativeai as genai
from ollama import Client

genai.configure( api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("API_KEY") )

phi_client = Client()
logger = logging.getLogger("apex.gemini")

def _extract_text(response) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""

def _judge_score(task: str, output: str) -> int:
    prompt = (
        "You are a strict judge.\n"
        "Score based on:\n"
        "- correctness (40%)\n"
        "- completeness (30%)\n"
        "- clarity (20%)\n"
        "- formatting (10%)\n\n"
        "Return ONLY a number (0-100).\n"
        "No explanation.\n\n"
        f"TASK:\n{task}\n\n"
        f"OUTPUT:\n{output}\n"
    )

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text = _extract_text(response)
        match = re.search(r"\b(100|[1-9]?\d)\b", text)
        if match:
            score = int(match.group(0))
            return max(0, min(100, score))
        logger.warning("gemini_invalid_score | raw=%s", text)
    except Exception as e:
        logger.warning("gemini_failed | error=%s", e)

    try:
        phi_response = phi_client.chat(model="phi3:mini",messages=[{"role": "user", "content": prompt}],options={    "temperature": 0.0,    "num_predict": 50,    "stop": ["\n"]},keep_alive=0)

        phi_text = (
            (phi_response.get("content") if isinstance(phi_response, dict) else "")
            or (phi_response.get("message", {}).get("content", "") if isinstance(phi_response, dict) else "")
            or getattr(getattr(phi_response, "message", None), "content", "")
            or getattr(phi_response, "content", "")
            or ""
        ).strip()
        match = re.search(r"\b(100|[1-9]?\d)\b", phi_text)
        if match:
            score = int(match.group(0))
            return max(0, min(100, score))
        logger.warning("phi_invalid_score | raw=%s", phi_text)
    except Exception as e:
        logger.warning("phi_failed | error=%s", e)
    logger.warning("judge_fallback_default | returning neutral score")
    return 50
    
def run_agent(merged_output: str, original_task: str, retries: int = 1) -> str:
    if retries <= 0:
        logger.warning("gemini_guard_triggered | returning original output")
        return merged_output
    try:
        score = _judge_score(original_task, merged_output)
        if score >= 60:
            logger.info("gemini_success | score=%s", score)
            return merged_output
        logger.warning("gemini_reroute | score=%s", score)
        try:
            from backend.app.agents.main_orchester import orchestrate
            rerun = orchestrate(original_task, use_quality_check=False)
            new_output = rerun.get("output", merged_output)
            return run_agent(new_output, original_task, retries - 1)
        except Exception as e:
            logger.warning("gemini_reroute_failed | error=%s", e)
            return merged_output
    except Exception as e:
        logger.warning("gemini_total_failure | error=%s", e)
        try:
            from backend.app.agents.phi_agent import judge_and_route
            return judge_and_route(original_task, merged_output)
        except Exception:
            return merged_output