from ollama import Client
import logging

client = Client()
logger = logging.getLogger("mistral_merger")

def _extract(response):
    if isinstance(response, dict):
        return response.get("content") or response.get("message", {}).get("content", "")
    return getattr(getattr(response, "message", None), "content", "") or ""


def merge_output(task: str, code_output: str, text_output: str):
    prompt = f"""
        You are a RESPONSE COMPOSER agent.

        TASK:
        {task}

        CODE OUTPUT:
        {code_output}

        TEXT OUTPUT:
        {text_output}

        RULES:
        - Do NOT change code logic
        - Preserve code EXACTLY as given
        - Wrap code inside proper markdown triple backticks
        - Do NOT modify spacing, indentation, or syntax
        - Only structure and organize
        - Combine outputs into ONE clean response
        - Use headings:
            1. Summary
            2. Code
            3. Explanation
        - Keep it concise and readable
        """

    try:
        response = client.chat(model="mistral",messages=[{"role": "user", "content": prompt}],options={"temperature": 0.4,"num_predict": 800,"stop": ["\n\n\n"],"num_ctx": 4096,"repeat_penalty": 1.1},keep_alive=0)
        text = _extract(response)
        if not text or len(text.strip()) < 20:
            logger.warning("mistral_invalid_output")
            return text_output if 'text_output' in locals() else task_text
        return text
    except Exception as e:
        logger.error(f"merge failed: {e}")
        return f"""
            ### Code
            {code_output}
            ### Explanation
            {text_output}
            """

def generate(task_text: str):
    prompt = f"""
        You are Mistral, a reasoning + explanation agent.
        RULES:
        - Be structured
        - Be concise
        - No hallucination
        - Max 500 words
        TASK:
        {task_text}
        """
    try:
        response = client.chat(model="mistral",messages=[{"role": "user", "content": prompt}],options={"temperature": 0.4,"num_predict": 800,"stop": ["</s>"],"num_ctx": 4096,"repeat_penalty": 1.1},keep_alive=60)
        text = _extract(response)
        logger.info("mistral_success | output_length=%s", len(text or ""))
        return text
    except Exception as e:
        logger.warning("mistral_fallback | error=%s", e)
        return f"[mistral fallback] {task_text}"
