from ollama import Client
import re
client = Client()

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


def judge_and_route(task: str, output: str) -> str:
    prompt = (
        "You are a strict judge.\n"
        f"Task:\n{task}\n\n"
        f"Output:\n{output}\n\n"
        "Return ONLY a number (0-100).\n"
        "No explanation,No extra wording, just a number or score."
    )
    try:
        response = client.chat(model="phi",messages=[{"role": "user", "content": prompt}],options={"temperature": 0, "num_predict": 50},keep_alive=0)
        score_text = _extract_content(response).strip()
        match = re.search(r"\d{1,3}", score_text or "")
        if not match:
            try:
                from backend.app.agents.llama3 import orchestrate as orc
                rerun = orc(task, useQualityCheck=False)
                return rerun.get("output", output)
            except Exception:
                return output
        score = max(0, min(100, int(match.group(0))))
        if score >= 60:
            return output
        else:
            try:
                from backend.app.agents.llama3 import orchestrate as orc
                rerun = orc(task, useQualityCheck=False)
                return rerun.get("output", output)
            except Exception:
                return output
    except Exception:
        try:
            from backend.app.agents.llama3 import orchestrate as orc
            rerun = orc(task, useQualityCheck=False)
            return rerun.get("output", output)
        except Exception:
            return output


def generate(task_text: str) -> str:
    try:
        response = client.chat(model="phi",messages=[{"role": "user", "content": task_text}],options={"temperature": 0, "num_predict": 500},keep_alive=0)
        return _extract_content(response)
    except Exception:
        return f"[phi_agent fallback] failed to process: {task_text}"
