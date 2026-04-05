import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from ollama import Client
from backend.app.agents.deepseek_agent import generate as deepseek_generate
from backend.app.agents.mistral_agent import generate as mistral_generate
from backend.app.agents.phi_agent import generate as phi_generate

client = Client()
CLASSIFICATION_TIMEOUT_SECONDS = 60

def _route_with_meta(task: str, tag: str):
    routes = {"CODE": ("deepseek", deepseek_generate),"TXT": ("mistral", mistral_generate),}
    selected_agent, runner = routes.get(tag, ("mistral", mistral_generate))
    return runner(task), selected_agent

def _fallback_with_meta(task: str):
    try:
        return phi_generate(task),"phi"
    except Exception:
        return "Fallback agents failed.", "phi"


def _classify(prompt: str) -> str:
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(client.chat,model="llama3:8b",messages=[{"role": "user", "content": prompt}],options={"temperature": 0, "num_predict": 100},keep_alive=0)
            return _extract_content(future.result(timeout=CLASSIFICATION_TIMEOUT_SECONDS))
    except Exception as e:
        raise RuntimeError(f"Classification failed: {e}")

def _build_decomposition_prompt(task_text: str) -> str:
    return (
        "You are a strict task decomposer.\n"
        "Read the task carefully and split the task or problem statement into 2 subtask or 2 sub-problem-statements only!\n"
        "Format rule after dividing the subtask give each subtask a heading above the subtask: CODE for code related statement or subtask and TXT for text based subtask or statement\n"
        "Do not add extra detail or new things , just precisely divide the statment into 2 parts, each part should be meaning-full clearly mentions the problem or task statement\n"
        "\nExample:\n"
        "CODE: Write a Python function that parses CSV data\n"
        "TXT: Explain what CSV parsing means and common use cases\n"
        "Don't add extra additions usedull(unmentioned) things or examples to the task rule, just precisely divide the statment with meaningness in each part \n"
        "\n Output only the two lines. No explanation, no preamble, no extra text. \n"
        f"\nTASK:\n{task_text}"
    )

#content extractor
def _extract_content(response) -> str:
    if isinstance(response, dict):
        return ( response.get("content") or response.get("message", {}).get("content", ""))
    message_obj = getattr(response, "message", None)
    if message_obj is not None: 
        msg_content = getattr(message_obj, "content", "")
        if isinstance(msg_content, str) and msg_content.strip():return msg_content
    return getattr(response, "content", "") or ""

def _parse_subtasks(llama_output: str,task_text:str):
    text=""
    code=""
    for line in llama_output.splitlines():
        if line.startswith("TXT"):
            text=line.replace("TXT:", "").strip()
        if line.startswith("CODE"):
            code=line.replace("CODE:", "").strip()
    if not code and not text:
            return task_text, task_text
    return code,text

#Gemini thingies
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

#orchester
def orchestrate(task_text: str,useQualityCheck:bool) -> dict:
    prompt = _build_decomposition_prompt(task_text)
    try:
        llama_output = _classify(prompt)
    except Exception:
        import time
        time.sleep(5)
        code_task, txt_task = task_text, task_text
        try:
            llama_output = _classify(prompt)
        except Exception:
            llama_output = None
    if llama_output:
        code_task, txt_task = _parse_subtasks(llama_output, task_text)
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        code_future = executor.submit(_route_with_meta, code_task, "CODE")
        txt_future = executor.submit(_route_with_meta,txt_task, "TXT")
        try:
            code_result, code_agent = code_future.result(timeout=60)
            if not _validate_output(code_result):
                code_result, code_agent = _fallback_with_meta(code_task)
        except (FuturesTimeoutError, Exception):
            code_result, code_agent = _fallback_with_meta(code_task)
        try:
            txt_result, txt_agent = txt_future.result(timeout=60)
            if not _validate_output(txt_result):
                txt_result, txt_agent = _fallback_with_meta(txt_task)
        except (FuturesTimeoutError, Exception):
            txt_result, txt_agent = _fallback_with_meta(txt_task)

    merged = f"[CODE RESULT]\n{code_result}\n\n[TXT RESULT]\n{txt_result}"
    try:
        if useQualityCheck:
            if not _check_gemini_quota():
                return {"output": merged,"agents_used": [code_agent, txt_agent],"fallback_used": False,"gemini_quota_remaining": 0,"warning": "Gemini quality check skipped: quota exhausted"}
            _decrement_gemini_quota()
            try:
                from backend.app.agents.gemini_agent import run_agent
                result = run_agent(merged, task_text)
                return {"output": result,"agents_used": [code_agent, txt_agent],"fallback_used": False,"gemini_quota_remaining": _GEMINI_QUOTA["remaining"]}
            except Exception as e:
                _refund_gemini_quota()
                return {"output": merged,"agents_used": [code_agent, txt_agent],"fallback_used": True,"gemini_quota_remaining": _GEMINI_QUOTA["remaining"],"error": f"Gemini quality check failed: {str(e)}"}
        return {"output": merged,"agents_used": [code_agent, txt_agent],"fallback_used": False,"gemini_quota_remaining": _GEMINI_QUOTA["remaining"]}
    except Exception:
        return {"output": merged,"agents_used": [code_agent,txt_agent],"fallback_used": False}

def _validate_output(text: str, min_length: int = 20) -> bool:
    return bool(text and len(text.strip()) >= min_length and "[No response]" not in text)
