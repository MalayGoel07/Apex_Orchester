import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from ollama import Client

from backend.app.agents.deepseek_agent import generate as deepseek_generate
from backend.app.agents.mistral_agent import generate as mistral_generate
from backend.app.agents.phi_agent import generate as phi_generate

client = Client()
CLASSIFICATION_TIMEOUT_SECONDS = 60


def _route_with_meta(task: str, tag: str):
    routes = {
        "CODE": ("deepseek", deepseek_generate),
        "TXT": ("mistral", mistral_generate),
    }
    selected_agent, runner = routes.get(tag, ("mistral", mistral_generate))
    return runner(task), selected_agent


def _fallback_with_meta(task: str):
    try:
        return phi_generate(task), "phi"
    except Exception:
        return "Fallback agents failed.", "phi"


def _classify(prompt: str) -> str:
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit( client.chat, model="llama3:8b", messages=[{"role": "user", "content": prompt}], options={"temperature": 0.7, "num_predict": 550}, keep_alive=0,)
            return _extract_content(future.result(timeout=CLASSIFICATION_TIMEOUT_SECONDS))
    except Exception as e:
        raise RuntimeError(f"Classification failed: {e}")


def _build_classification_prompt(task_text: str) -> str:
    return (
        "You are a strict task Classifier.\n"
        "Read and analyze the task carefully and respond with ONLY ONE word:\n"
        "- CODE: if the task requires writting,debugging or explaining code related statements.\n"
        "- TEXT: if the task is purely text-based(explanation,summary,creative writing).\n"
        "- MIXED: if the task needs both code AND text explanation.\n"
        "Do not add extra detail or new things , just precisely RESPOND WITH ONLY ONE WORD please.\n"
        "\nExample:\n"
        "CODE: Write a Python function that parses CSV data\n"
        "TXT: Explain what CSV parsing means and common use cases\n"
        "MIXED: Write python function that parses CSV data and also Explain what is CSV prasing.\n"
        f"\nTASK:\n{task_text} please."
    )


def _build_decomposition_prompt(task_text: str) -> str:
    return (
        "You are a strick task decomposer. Split the following task into exactly two independent subtasks.\n"
        "\nSTRICT OUTPUT FORMATE:\n"
        "CODE:[code-related subtask here]\n"
        "TXT:[text-related subtask here]\n"
        "\nRULES\n"
        "-Output ONLY these two lines.No markdown,No greetings,No numbers,No explanations.\n"
        "-CODE line must contain only the programming/implementation request.\n"
        "-TXT line must contain only the explanation/analysis/writing requests.\n"
        "-if the task doesn't fit one category,write 'NONE' for that line.\n"
        "\nEXAMPLES\n"
        "CODE: Write a Python function that parse CSV data,\n"
        "TXT: EXplain what CSV parasing means and common use cases.\n"
        f"\nTASK:\n{task_text} please."
    )


def _extract_content(response) -> str:
    if isinstance(response, dict):
        return response.get("content") or response.get("message", {}).get("content", "")
    message_obj = getattr(response, "message", None)
    if message_obj is not None:
        msg_content = getattr(message_obj, "content", "")
        if isinstance(msg_content, str) and msg_content.strip():
            return msg_content
    return getattr(response, "content", "") or ""


def _parse_subtasks(llama_output: str, task_text: str):
    text = ""
    code = ""
    for line in llama_output.splitlines():
        if line.startswith("TXT"):
            text = line.replace("TXT:", "").strip()
        if line.startswith("CODE"):
            code = line.replace("CODE:", "").strip()
    if not code and not text:
        return task_text, task_text
    return code, text


def get_decision(classification: str) -> list:
    classification = classification.strip().upper()
    if "CODE" in classification and "MIXED" not in classification and "TEXT" not in classification:
        return ["deepseek"], False
    elif "TEXT" in classification and "CODE" not in classification and "MIXED" not in classification:
        return ["mistral"], False
    else:
        return ["deepseek", "mistral"], True


_GEMINI_QUOTA = {"remaining": 10}
def _check_gemini_quota() -> bool:
    return _GEMINI_QUOTA.get("remaining", 0) > 0
def _decrement_gemini_quota():
    current = _GEMINI_QUOTA.get("remaining", 0)
    if current > 0:
        _GEMINI_QUOTA["remaining"] = current - 1
def _refund_gemini_quota():
    current = _GEMINI_QUOTA.get("remaining", 0)
    _GEMINI_QUOTA["remaining"] = min(current + 1, 10)


def orchestrate(task_text: str, useQualityCheck: bool) -> dict:
    agent_used = []
    fallback_used = False
    try:
        classification_prompt = _build_classification_prompt(task_text)
        classification = _classify(classification_prompt)
        models_to_use, need_decomposition = get_decision(classification)

        if need_decomposition:
            decomposition_prompt = _build_decomposition_prompt(task_text)
            llama_output = _classify(decomposition_prompt)
            code_task, text_task = _parse_subtasks(llama_output, task_text)
            time.sleep(1)
        else:
            code_task = text_task = task_text

        results = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            if "deepseek" in models_to_use:
                futures["code"] = executor.submit(_route_with_meta, code_task, "CODE")
            if "mistral" in models_to_use:
                futures["text"] = executor.submit(_route_with_meta, text_task, "TXT")

            for task_type, future in futures.items():
                try:
                    result, agent = future.result(timeout=60)
                    if not _valid_output(result):
                        result, agent = _fallback_with_meta(task_text)
                        fallback_used = True
                    results[task_type] = result
                    agent_used.append(agent)
                except (FuturesTimeoutError, Exception):
                    result, agent = _fallback_with_meta(task_text)
                    results[task_type] = result
                    agent_used.append(agent)
                    fallback_used = True

        if "code" in results and "text" in results:
            final_output = f"[CODE RESULT]\n{results['code']}\n\n[TEXT RESULT]\n{results['text']}"
        elif "code" in results:
            final_output = results["code"]
        else:
            final_output = results.get("text", "")

        if useQualityCheck and _check_gemini_quota():
            _decrement_gemini_quota()
            try:
                from backend.app.agents.gemini_agent import run_agent
                quality_check = run_agent(final_output, task_text)
                return {"output": quality_check,"agents_used": agent_used,"classification": classification,"gemini_quota_remaining": _GEMINI_QUOTA["remaining"],}
            except Exception as e:
                _refund_gemini_quota()
                return {"agents_used": agent_used,"output": final_output,"fallback_used": fallback_used,"classification": classification,"error": f"Quality check failed: {str(e)}","gemini_quota_remaining": _GEMINI_QUOTA["remaining"],}
        return {"output": final_output,"agents_used": agent_used,"fallback_used": fallback_used,"classification": classification,"gemini_quota_remaining": _GEMINI_QUOTA["remaining"],}
    except Exception as e:
        final_output, _ = _fallback_with_meta(task_text)
        return {"output": final_output,"agents_used": ["phi"],"fallback_used": True,"error": str(e),}


def _valid_output(text: str, min_length: int = 20) -> bool:
    if not text or not text.strip():
        return False
    stripped = text.strip().lower()
    if len(stripped) < min_length:
        return False
    start_snippet = stripped[:120].lower()
    refusal = ["i'm sorry","i can't","i cannot","i apologize","unfortunately","as an ai","i don't have ability","i m unable",]
    if any(start_snippet.startswith(p) for p in refusal):
        return False
    crash = ["traceback(most recent call)","error:","exception:","killed","segmentation fault","the model is not loaded","cuda error","out of memory",]
    if any(m in start_snippet for m in crash):
        return False
    if stripped.endswith((".", ":", "(", "[", "{", "-", "...")) and len(stripped) < 150:
        return False
    return True
