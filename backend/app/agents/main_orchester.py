import json
import logging
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Dict, List, Tuple, Optional
from ollama import Client
from backend.app.agents.qwen_agent import generate as qwen_generator
from backend.app.agents.mistral_agent import generate as mistral_generate
from backend.app.agents.phi_agent import generate as phi_generate

client = Client()
CLASSIFICATION_TIMEOUT_SECONDS = 60
AGENT_TIMEOUT_SECONDS = 120
MIN_OUTPUT_LENGTH = 20
logger = logging.getLogger("apex.orchestrator")
CLASSIFIER_MODEL = "phi3:mini"
CLASSIFIER_KEEP_ALIVE = 45

class QuotaManager:
    def __init__(self, max_quota: int = 10):
        self._quota = max_quota
        self._lock = threading.Lock()
    def check(self) -> bool:
        with self._lock:
            return self._quota > 0
    def decrement(self) -> bool:
        with self._lock:
            if self._quota > 0:
                self._quota -= 1
                return True
            return False
    def refund(self):
        with self._lock:
            if self._quota < 10:
                self._quota += 1
    @property
    def remaining(self) -> int:
        with self._lock:
            return self._quota
_gemini_quota = QuotaManager()
ClassificationTag = Literal["code", "text", "mixed","website","learn"]

def _log(event: str, data: Optional[Dict] = None):
    data = data or {}
    data["_ts"] = round(time.time() % 10000, 2)
    payload = json.dumps(data, ensure_ascii=False, default=str)
    logger.info("%s | %s", event, payload)
    print(f"[ORCH_LOG] {event} | {payload}")


def _extract_content(response) -> str:
    if isinstance(response, dict):
        return response.get("content") or response.get("message", {}).get("content", "")
    msg = getattr(response, "message", None)
    if msg:
        return getattr(msg, "content", "") or ""
    return getattr(response, "content", "") or ""

def _parse_json_output(raw: str, expected_keys: List[str]) -> Optional[Dict]:
    try:
        match = re.search(r'\{[\s\S]*?\}', raw.strip())
        if match:
            data = json.loads(match.group())
            if all(k in data for k in expected_keys):
                return data
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE)
        data = json.loads(cleaned)
        if all(k in data for k in expected_keys):
            return data
    except (json.JSONDecodeError, AttributeError):
        pass
    return None

def _valid_output(text: Optional[str], min_len: int = MIN_OUTPUT_LENGTH) -> bool:
    if not text or len(text.strip()) < min_len:
        return False
    t_lower = text[:200].lower()
    bad_signals = ["i'm sorry", "i cannot", "i can't", "as an ai","error:", "exception", "traceback", "out of memory"]
    return not any(bad in t_lower for bad in bad_signals)

def _merge_results(code: Optional[str], text: Optional[str]) -> str:
    parts = []
    if text and text.strip():
        parts.append(f"-> Explanation\n{text.strip()}")
    if code and code.strip():
        parts.append(f"-> Implementation\n{code.strip()}")
    return "\n\n".join(parts) if parts else "No output generated. Try again later!"


def _build_classification_prompt(task_text: str) -> str:
    return """You are a task classifier. Classify the task below into EXACTLY ONE tag among the TAGS.

        - website: ANY task involving components, buttons, forms, pages, UI, React, HTML, CSS, frontend, backend, API, full-stack, or web-related code. When in doubt, use this. Overrides all other tags.
        - learn: ANY task involving a syllabus, curriculum, or topic where the user wants study material. This includes: question papers, viva questions, theory notes, lecture content, progressive questions (easy to hard), resources, or any educational output. Triggers when user uploads or pastes a syllabus OR asks for QP, viva, notes, lecture, resources for any subject. Overrides code and text tags.
        - code: needs only pure logic code (functions, scripts, algorithms) — NOT a web app, NOT a component, NOT study material
        - text: needs only explanation, documentation, or analysis — no code at all
        - mixed: needs BOTH a code implementation AND an explanation — NOT a web app, NOT study material

        RULES:
        1. Output ONLY a JSON object, no markdown, no extra text.
        2. Use the tag string exactly as written above.
        3. If the task involves building anything web-related, ALWAYS use "website".
        4. Default to "text" when uncertain.
        5. If the user mentions "syllabus", "QP", "question paper", "viva", "notes", "lecture", "resources" → ALWAYS use "learn"
        6. If the task mentions a component, button, form, page, or any UI element → ALWAYS use "website"

        OUTPUT FORMAT:
        {{"tag": "<exact_tag>"}}

        TASK:
        {task}""".format(task=task_text)

def _build_decomposition_prompt(task_text: str) -> str:
    return """You are a task splitter. Split the mixed task below into exactly two subtasks.

        Part 1 (tag: "text") — explanation, theory, or documentation only. No code.
        Part 2 (tag: "code") — implementation only. No explanations.

        Rules:
        - Zero overlap between parts.
        - Output ONLY a valid JSON object, no markdown, no preamble.

        OUTPUT FORMAT:
        {{"part_1": {{"tag": "text", "scope": "..."}}, "part_2": {{"tag": "code", "scope": "..."}}}}

        TASK:
        {task}""".format(task=task_text)


def _classify(task_text: str) -> ClassificationTag:
    prompt = _build_classification_prompt(task_text)
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(client.chat,model="phi3:mini",messages=[{"role": "user", "content": prompt}],options={"temperature": 0.0, "num_predict": 50, "top_p": 0.9},keep_alive=120)
            result = future.result(timeout=CLASSIFICATION_TIMEOUT_SECONDS)
        raw = _extract_content(result).strip()
        parsed = _parse_json_output(raw, expected_keys=["tag"])
        if parsed:
            tag = parsed["tag"]
            if tag in ("code", "text", "mixed","website","learn"):
                _log("classification_success", {"tag": tag})
                return tag
        _log("classification_parse_failed", {"raw": raw[:200]})
    except Exception as e:
        _log("classification_failed", {"error": str(e)})
    return "text"

def _decompose_task(task_text: str) -> Tuple[str, str]:
    prompt = _build_decomposition_prompt(task_text)
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(client.chat,model=CLASSIFIER_MODEL,messages=[{"role": "user", "content": prompt}],options={"temperature": 0.0, "num_predict": 512, "top_p": 0.9},keep_alive=CLASSIFIER_KEEP_ALIVE,)
            resp = future.result(timeout=CLASSIFICATION_TIMEOUT_SECONDS)
        raw = _extract_content(resp).strip()
        parsed = _parse_json_output(raw, expected_keys=["part_1", "part_2"])
        if parsed:
            text_task = parsed["part_1"].get("scope", task_text)
            code_task = parsed["part_2"].get("scope", task_text)
            _log("decomposition_success", {"text_task_preview": text_task[:80],"code_task_preview": code_task[:80],})
            return code_task,text_task
        _log("decomposition_parse_failed", {"raw_preview": raw[:100]})
    except Exception as e:
        _log("decomposition_error", {"error": str(e)[:150]})
    return task_text, task_text


def _fallback(task: str) -> Tuple[str, str]:
    try:
        result = phi_generate(task)
        if _valid_output(result):
            _log("fallback_success", {"agent": "phi", "output_length": len(result)})
            return result, "phi"
    except Exception as e:
        _log("fallback_exception", {"agent": "phi", "error": str(e)})
    return "Unable to complete request. Please try rephrasing or breaking down the task.", "phi"

def _run_agent(agent_name: str, task: str) -> Tuple[str, str]:
    if agent_name == "deepseek":
        return qwen_generator(task), "deepseek"
    elif agent_name == "mistral":
        return mistral_generate(task), "mistral"
    elif agent_name == "phi":
        return phi_generate(task), "phi"
    return _fallback(task)


def _quality_check(final_output: str, task_text: str) -> str:
    try:
        from backend.app.agents.gemini_agent import run_agent
        return run_agent(final_output, task_text)
    except Exception as e:
        _log("quality_check_error", {"error": str(e)})
        return final_output
    

def orchestrate(task_text: str, use_quality_check: bool = False) -> Dict:
    agent_trace: List[str] = []
    fallback_used = False
    _log("task_received", {"task_preview": task_text[:100] + ("..." if len(task_text) > 100 else ""),"classifier_model": CLASSIFIER_MODEL,})

    try:
        classification = _classify(task_text)
        _log("classified", {"classification": classification})
        results: Dict[str, str] = {}

        if classification == "text":
            _log("routing", {"strategy": "text_only", "agent": "mistral"})
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_run_agent, "mistral", task_text)
                try:
                    result, agent = future.result(timeout=AGENT_TIMEOUT_SECONDS)
                    if not _valid_output(result):
                        result, agent = _fallback(task_text)
                        fallback_used = True
                    results["text"] = result
                    agent_trace.append(agent)
                except Exception as e:
                    _log("agent_error", {"error": str(e)})
                    result, agent = _fallback(task_text)
                    results["text"] = result
                    fallback_used = True
                    agent_trace.append(agent)

        elif classification == "code":
            _log("routing", {"strategy": "code_only", "agent": "deepseek"})
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_run_agent, "deepseek", task_text)
                try:
                    result, agent = future.result(timeout=AGENT_TIMEOUT_SECONDS)
                    if not _valid_output(result):
                        result, agent = _fallback(task_text)
                        fallback_used = True
                    results["code"] = result
                    agent_trace.append(agent)
                except Exception as e:
                    _log("agent_error", {"error": str(e)})
                    result, agent = _fallback(task_text)
                    results["code"] = result
                    fallback_used = True
                    agent_trace.append(agent)
        elif classification == "learn":
            _log("routing", {"strategy": "switching to learn orchestrator"})
            from backend.app.agents.learn_orchester import learn_pipeline
            final_output = learn_pipeline(task_text)
            return {"output": final_output,"agents_used": ["multi_agents"],"classification": classification,"classifier_model": CLASSIFIER_MODEL,"fallback_used": False,"gemini_quota_remaining": _gemini_quota.remaining,"success": True,}
        elif classification == "website":
            _log("routing", {"strategy": "switching to website orchestrator"})
            from backend.app.agents.website_orchester import multi_agents
            final_output = multi_agents(task_text)
            return {"output": final_output,"agents_used": ["multi_agents"],"classification": classification,"classifier_model": CLASSIFIER_MODEL,"fallback_used": False,"gemini_quota_remaining": _gemini_quota.remaining,"success": True,}
        else:
            _log("routing", {"strategy": "mixed_decompose", "decomposer": CLASSIFIER_MODEL})
            code_task, text_task = _decompose_task(task_text)
            _log("subtasks_prepared", {"text_subtask": text_task[:80],"code_subtask": code_task[:80],})
            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = {"code": ex.submit(_run_agent, "deepseek", code_task),"text": ex.submit(_run_agent, "mistral", text_task),}
                for task_key, future in futures.items():
                    try:
                        result, agent = future.result(timeout=AGENT_TIMEOUT_SECONDS)
                        if not _valid_output(result):
                            _log("invalid_output", {"task": task_key, "agent": agent})
                            fallback_task = code_task if task_key == "code" else text_task
                            result, agent = _fallback(fallback_task)
                            fallback_used = True
                        else:
                            _log("agent_success", {"task": task_key,"agent": agent,"output_length": len(result),})
                        results[task_key] = result
                        if agent not in agent_trace:
                            agent_trace.append(agent)
                    except Exception as e:
                        _log("agent_execution_error", {"task": task_key, "error": str(e)})
                        fallback_task = code_task if task_key == "code" else text_task
                        result, agent = _fallback(fallback_task)
                        results[task_key] = result
                        fallback_used = True
                        if agent not in agent_trace:
                            agent_trace.append(agent)
        final_output = _merge_results(results.get("code", ""), results.get("text", ""))
        if len(final_output) < 100:
            try:
                improved = phi_generate("Improve this output:\n" + final_output)
                if _valid_output(improved):
                    final_output = improved
            except Exception:
                pass
        _log("output_merged", {"length": len(final_output)})

        if use_quality_check and _gemini_quota.check():
            try:
                _gemini_quota.decrement()
                final_output = _quality_check(final_output, task_text)
                _log("quality_check_applied", {})
            except Exception as e:
                _gemini_quota.refund()
                _log("quality_check_failed", {"error": str(e)})
        return {"output": final_output,"agents_used": agent_trace,"classification": classification,"classifier_model": CLASSIFIER_MODEL,"fallback_used": fallback_used,"gemini_quota_remaining": _gemini_quota.remaining,"success": True,}
    except Exception as e:
        _log("orchestrator_crash", {"error": str(e), "type": type(e).__name__})
        fallback, agent = _fallback(task_text)
        return {"output": fallback,"agents_used": [agent],"classification": "error","classifier_model": CLASSIFIER_MODEL,"fallback_used": True,"error": str(e),"gemini_quota_remaining": _gemini_quota.remaining,"success": False,}

def generate(task_text: str, use_quality_check: bool = False) -> Dict:
    return orchestrate(task_text, use_quality_check)