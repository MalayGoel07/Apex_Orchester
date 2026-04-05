from ollama import Client
from backend.app.agents.mistral_agent import generate as mistral_generate

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

    return "[deepseek_agent] No response"


def generate(task_text: str) -> str:
    prompt = (
        "You are an expert coding AI agent who handles the code related task.\n"
        "your responsibilties.\n"
        "understand the problem deeply before solving.\n"
        "Write clean efficient and production ready code or detailed explaination about it if asked.\n"
        "follow medium practice for error handling and readability.\n"
        "Optimise performance accordingly if needed.\n"
        "\nInstructions.\n"
        "max word limit is 250words\n"
        "Return only one final answer if its a coding return (code only) or else detailed explanation with 1 code example\n"
        "also ensure that code is correct, readable and runnable.\n\n"
        f"TASK:\n{task_text}"
        )
    try:
        response = client.chat(model="deepseek-coder", messages=[{"role": "user", "content": prompt}],options={"temperature": 0, "num_predict": 400},keep_alive=0)
        text = _extract_content(response)
        if text == "[deepseek_agent] No response":
            return mistral_generate(task_text)
        return text
    except Exception:
        return mistral_generate(task_text)
