import re
import os
from google import generativeai as genai
from ollama import Client

genai.configure(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("API_KEY"))
phi_client = Client()


def _judge_score(task: str, output: str) -> int:
    prompt = (
        "You are a strict judge.\n"
        "Return only one integer score from 0 to 100.\n"
        "No extra text.\n\n"
        f"TASK:\n{task}\n\n"
        f"OUTPUT:\n{output}\n"
    )
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text = (getattr(response, "text", "") or "").strip()
        match = re.search(r"\d{1,3}", text)
        if match:
            return max(0, min(100, int(match.group(0))))
    except Exception:
        pass

    phi_response = phi_client.chat(model="phi",messages=[{"role": "user", "content": prompt}],options={"temperature": 0, "num_predict": 50},keep_alive=0,)
    phi_text = (
        (phi_response.get("content") if isinstance(phi_response, dict) else "")
        or (phi_response.get("message", {}).get("content", "") if isinstance(phi_response, dict) else "")
        or getattr(getattr(phi_response, "message", None), "content", "")
        or getattr(phi_response, "content", "")
        or ""
    ).strip()
    phi_match = re.search(r"\d{1,3}", phi_text)
    if not phi_match:
        raise RuntimeError("Both Gemini and Phi failed to return a valid score.")
    return max(0, min(100, int(phi_match.group(0))))


def run_agent(merged_output: str, original_task: str) -> str:
    try:
        score = _judge_score(original_task, merged_output)
        if score >= 60:
            return merged_output
        from backend.app.agents.llama3 import orchestrate
        rerun = orchestrate(original_task, useQualityCheck=False)
        return rerun.get("output", merged_output)
    except Exception:
        from backend.app.agents.phi_agent import judge_and_route
        return judge_and_route(original_task, merged_output)
