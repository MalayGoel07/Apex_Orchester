from ollama import Client
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
    return "[mistral_agent] No response"


def generate(task_text: str) -> str:
    prompt=(
        "Write your name Mistral as 1st word to start of with.\n"
        "You are a highly intelligent ai reasoning and tex-processing agent.\n"
        "\nyour responsibilities:\n"
        "Understand the task deeply."
        "Provide accurate,structured and concide response.\n"
        "think logically and avoid assumptions.\n"
        "Your capabilities Explanation,planning,summarization and dicision making.\n"
        "\nrules:\n"
        "Be clear and structured.\n"
        "max word limit is 250words\n"
        "Ensure correctness and logic.\n"
        "Give structured output or answers (use steps or bullets if needed).\n"
        "keep answer concise but complete.\n\n"
        f"TASK:\n{task_text}"
    )
    try:
        response = client.chat(model="mistral", messages=[{"role": "user", "content": prompt}],options={"temperature": 0.8, "num_predict": 600},keep_alive=0)
        text = _extract_content(response)
        if text == "[mistral_agent] No response":
            from backend.app.agents.llama3 import orchestrate
            fallback = orchestrate(task_text, useQualityCheck=False)
            return fallback.get("output", "[mistral_agent] No response")
        return text
    except Exception:
        from backend.app.agents.phi_agent import generate as phi_generate
        return phi_generate(task_text)
