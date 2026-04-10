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
    prompt = (
        "You are an expert coding AI agent who handles the code related task.\n"
        "your responsibilities.\n"
        "understand the problem deeply before solving.\n"
        "Write clean efficient and production ready code or detailed explaination about it if asked.\n"
        "follow medium practice for error handling and readability.\n"
        "Optimise performance accordingly if needed.\n"
        "\nInstructions.\n"
        "Return only one final answer if its a coding return (code only) or else detailed explanation with 1 code example\n"
        "also ensure that code is correct, readable and runnable.\n\n"
        f"TASK:\n{task_text}"
        )
    try:
        response = client.chat(model="deepseek-coder:6.7b", messages=[{"role": "user", "content": prompt}],options={"temperature": 0.1,"top_p": 0.9,"repeat_penalty": 1.1,"num_predict": 1000,"stop": ["\n\n\n"],"frequency_penalty":0,"num_ctx": 4096},keep_alive=60)
        text = _extract_content(response)
        if not text or len(text.strip()) < 20:
            logger.warning("deepseek_fallback | reason=no_response")
            return mistral_generate(task_text)
        logger.info("deepseek_success | output_length=%s", len(text or ""))
        return text
    except Exception as e:
        logger.warning("deepseek_fallback | reason=exception error=%s", e)
        return mistral_generate(task_text)
