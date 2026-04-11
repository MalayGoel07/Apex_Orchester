from ollama import Client
import logging
from backend.app.agents.mistral_agent import generate as mistral_generate

client = Client()
logger = logging.getLogger("apex.deepseek")


def _extract_content(response) -> str:
    if isinstance(response, dict):
        return response.get("content") or response.get("message", {}).get("content", "")
    return getattr(getattr(response, "message", None), "content", "") or ""

def generate(task_text: str) -> str:
    prompt = f'''You are an expert coding AI agent handling code-related tasks.
    Your responsibilities:
    - Understand the problem deeply before solving.
    - Write clean, efficient, production-ready code or detailed explanations when asked.
    - Follow best practices for error handling and readability.
    - Optimize performance when needed.

    Instructions:
    - Ensure code is correct, readable, and runnable.

    TASK:
    {task_text}'''
    try:
        response = client.chat(model="deepseek-fast", messages=[{"role": "user", "content": prompt}],options={"temperature": 0.1,"top_p": 0.9,"repeat_penalty": 1.1,"num_predict": 1000,"stop": ["\n\n\n"],"frequency_penalty":0},keep_alive=30)
        text = _extract_content(response)
        if not text or len(text.strip()) < 20:
            logger.warning("deepseek_fallback | reason=no_response")
            return mistral_generate(task_text)
        logger.info("deepseek_success | output_length=%s", len(text or ""))
        return text
    except Exception as e:
        logger.warning("deepseek_fallback | reason=exception error=%s", e)
        return mistral_generate(task_text)
