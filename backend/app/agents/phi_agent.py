from ollama import Client
import re
import logging

client = Client()
logger = logging.getLogger("apex.phi")

def _extract_content(response) -> str:
    if isinstance(response, dict):
        direct = response.get("content")
        if isinstance(direct, str) and direct.strip():
            return direct
        message = response.get("message", {})
        if isinstance(message, dict):
            msg_content = message.get("content", "")
            if isinstance(msg_content, str) and msg_content.strip():
                return msg_content
    message_obj = getattr(response, "message", None)
    if message_obj is not None:
        msg_content = getattr(message_obj, "content", "")
        if isinstance(msg_content, str) and msg_content.strip():
            return msg_content
    direct_obj = getattr(response, "content", "")
    if isinstance(direct_obj, str) and direct_obj.strip():
        return direct_obj
    return "[phi_agent] No response"

def judge_and_route(task: str, output: str, retries: int = 1) -> str:
    if retries <= 0:
        logger.warning("phi_guard_triggered | returning original output")
        return output

    prompt = (
        "You are a strict evaluator.\n\n"
        f"Task:\n{task}\n\n"
        f"Output:\n{output}\n\n"
        "Score based on:\n"
        "- correctness (40%)\n"
        "- completeness (30%)\n"
        "- clarity (20%)\n"
        "- formatting (10%)\n\n"
        "Return ONLY a number (0-100).\n"
        "No explanation. No text."
    )

    try:
        response = client.chat(
            model="phi3:mini",
            messages=[{"role": "user", "content": prompt}],
            options={ "temperature": 0.0,"num_predict": 50, "stop": ["\n"]},keep_alive=120)
        score_text = _extract_content(response).strip()
        match = re.search(r"\b(100|[1-9]?\d)\b", score_text)
        if not match:
            logger.warning("phi_invalid_score | raw=%s", score_text)
            return output
        score = int(match.group(0))
        logger.info("phi_score | score=%s", score)
        if score >= 60:
            return output
        logger.warning("phi_reroute | score=%s", score)
        try:
            from backend.app.agents.llama3 import orchestrate as orc
            rerun = orc(task, use_quality_check=False)
            new_output = rerun.get("output", output)
            return judge_and_route(task, new_output, retries - 1)
        except Exception as e:
            logger.warning("phi_reroute_failed | error=%s", e)
            return output
    except Exception as e:
        logger.warning("phi_judge_failed | error=%s", e)
        return output

def generate(task_text: str) -> str:
    try:
        response = client.chat(
            model="phi3:mini",
            messages=[{"role": "user", "content": task_text}],
            options={"temperature": 0.4,"num_predict": 500,"num_ctx": 4096},keep_alive=120)
        text = _extract_content(response)
        logger.info("phi_generate_success | length=%s", len(text or ""))
        if not text.strip():
            return "[phi_agent] Empty response"
        return text
    except Exception as e:
        logger.warning("phi_generate_failed | error=%s", e)
        return f"[phi_agent fallback] failed to process task"