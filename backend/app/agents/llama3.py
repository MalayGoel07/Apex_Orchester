import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import Literal, Dict, List, Tuple, Optional
from ollama import Client
from backend.app.agents.deepseek_agent import generate as deepseek_generate
from backend.app.agents.mistral_agent import generate as mistral_generate
from backend.app.agents.phi_agent import generate as phi_generate

client = Client()
CLASSIFICATION_TIMEOUT_SECONDS = 45
LARGE_CODE_TIMEOUT_SECONDS = 90
AGENT_TIMEOUT_SECONDS = 120
MIN_OUTPUT_LENGTH = 20
logger = logging.getLogger("apex.orchestrator")

class QuotaManager:
    def __init__(self, max_quota: int = 10):
        self._quota = max_quota
        self._lock = threading.Lock() if threading else None
    def check(self) -> bool:
        if self._lock:
            with self._lock:
                return self._quota > 0
        return self._quota > 0
    def decrement(self) -> bool:
        if self._lock:
            with self._lock:
                if self._quota > 0:
                    self._quota -= 1
                    return True
                return False
        if self._quota > 0:
            self._quota -= 1
            return True
        return False
    def refund(self):
        if self._lock:
            with self._lock:
                if self._quota < 10:
                    self._quota += 1
        elif self._quota < 10:
            self._quota += 1
    @property
    def remaining(self) -> int:
        return self._quota

_gemini_quota = QuotaManager()
ClassificationTag = Literal[ "code", "text", "mixed (code + text)"]

def _log(event: str, data: Optional[Dict] = None):
    payload = json.dumps(data or {}, ensure_ascii=False, default=str)
    logger.info("%s | %s", event, payload)
    print(f"[ORCH_LOG] {event} | {payload}")

#Extractor
def _extract_content(response) -> str:
    if isinstance(response, dict):
        return (response.get("content") or response.get("message", {}).get("content", ""))
    msg = getattr(response, "message", None)
    if msg:
        return getattr(msg, "content", "") or ""
    return getattr(response, "content", "") or ""

def _parse_json_output(raw: str, expected_keys: List[str]) -> Optional[Dict]:
    try:
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE)
        data = json.loads(cleaned)
        if all(k in data for k in expected_keys):
            return data
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            data = json.loads(match.group())
            if all(k in data for k in expected_keys):
                return data
    except (json.JSONDecodeError, AttributeError):
        pass
    return None

def _build_classification_prompt(task_text: str) -> str:
    return """
        You are a precise Task Classifier AI. Your ONLY job is to analyze the given task description and assign EXACTLY ONE tag from the predefined list below. Base your decision strictly on task scope, complexity, and required output type.

        🏷️ TAG DEFINITIONS:
        - code: Requires building a complete system, multi-file project, full-stack app, or complex architecture. Demands significant development time, multiple components, or substantial effort. (e.g., "build a full e-commerce website", "create a microservice-based inventory system") or Requires a single function, algorithm, script, snippet, or isolated solution. Focused, self-contained, typically <200 lines or 1-2 files. (e.g., "write binary search code", "create a Python script to rename files")
        - text: Purely conceptual, explanatory, analytical, or documentation-focused with ZERO coding requirements. (e.g., "explain how HTTP works", "describe agile methodology", "write a project proposal")
        - mixed (code + text): Requires building a substantial codebase/project AND providing detailed architectural explanations, documentation, or step-by-step breakdowns. (e.g., "build a large webapp and explain it in detail", "create a real-time chat system and document its scaling strategy") or or Requires both a clear explanation/documentation AND a small, focused code implementation. (e.g., "explain binary search and write its code", "describe JWT auth flow and show a minimal login endpoint")

        ⚙️ DECISION RULES FOR MAX PRECISION:
        1. Assign EXACTLY ONE tag. Never combine, modify, or invent tags.
        2. Match the tag string EXACTLY as written above. Case-sensitive.
        3. If the task mentions both code and explanation, first judge if the code scope is "small" or "large", then apply the correct mixed tag.
        4. Ignore stylistic fluff. Focus only on technical scope and deliverables.
        5. If uncertain between "small" and "large" code, default to "small code" unless multi-component architecture is explicitly stated.

        📤 OUTPUT FORMAT:
        Return ONLY a valid JSON object. No markdown, no extra text, no explanations.
        {{
          "tag": "<exact_tag>"
        }}

        🔍 INPUT TASK:
        {task}
        """.format(task=task_text)

def _build_decomposition_prompt(task_text: str) -> str:
    return """
        You are a Precision Task Splitter AI. Your ONLY job is to analyze a given mixed task (containing both explanation/documentation and code implementation) and split it into EXACTLY TWO distinct, non-overlapping subtasks.

        SPLITTING LOGIC:
        - Part 1 (Text): Focuses SOLELY on conceptual explanation, theory, architecture, documentation, or step-by-step breakdown. NO code snippets or implementation details.
        - Part 2 (Code): Focuses SOLELY on writing the actual implementation. Tag it based on scope:

        PRECISION RULES:
        1. Output EXACTLY two subtasks. Never merge, skip, or create extras.
        2. Part 1 tag MUST be "text". Part 2 tag MUST be either "small code" or "large code".
        3. Ensure ZERO overlap. Text explains "what/why/how it works". Code delivers "the actual implementation".
        4. Use clear, actionable language. Specify exact deliverables for each part.
        5. Ignore stylistic fluff. Focus strictly on technical boundaries and scope.

        OUTPUT FORMAT:
        Return ONLY a valid JSON object. Do NOT use markdown formatting (no ```json). Do NOT add any text before or after.
        {{
          "part_1": {{
            "tag": "text",
            "title": "...",
            "scope": "...",
            "deliverables": ["...", "..."]
          }},
          "part_2": {{
            "tag": "code",
            "title": "...",
            "scope": "...",
            "deliverables": ["...", "..."]
          }}
        }}

        🔍 INPUT TASK:
        {task}
        """.format(task=task_text)

def _classify(prompt: str) -> Optional[ClassificationTag]:
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit( client.chat, model="llama3:8b", messages=[{"role": "user", "content": prompt}], options={"temperature": 0.0, "num_predict": 120, "top_p": 0.9,"num_ctx": 4096}, keep_alive=0)
            result = future.result(timeout=CLASSIFICATION_TIMEOUT_SECONDS)
        raw_content = _extract_content(result).strip()
        parsed = _parse_json_output(raw_content, expected_keys=["tag"])
        
        if parsed and "tag" in parsed:
            tag = parsed["tag"].strip()
            valid_tags = ["code", "text","mixed (code + text)"]
            if tag in valid_tags:
                return tag
        _log("classification_parse_failed", {"raw": raw_content[:200]})
        return "text"
    except Exception as e:
        _log("classification_failed", {"error": str(e), "type": type(e).__name__})
        return "text"

def _route_models(classification: ClassificationTag) -> Tuple[List[str], bool]:
    mapping = {
        "code": (["deepseek"], False),
        "text": (["mistral"], False),
        "mixed (code + text)": (["deepseek", "mistral"], True),
    }
    return mapping.get(classification, (["mistral"], False))

def _parse_decomposition(output: str, original_task: str) -> Tuple[str, str]:
    parsed = _parse_json_output(output, expected_keys=["part_1", "part_2"])
    if not parsed:
        return original_task, original_task
    try:
        part1 = parsed["part_1"]
        part2 = parsed["part_2"]
        text_scope = part1.get("scope", part1.get("title", "Explain the concept"))
        code_scope = part2.get("scope", part2.get("title", "Implement the solution"))
        return code_scope, text_scope
    except (KeyError, TypeError, AttributeError):
        _log("decomposition_parse_error", {"parsed": parsed})
        return original_task, original_task
    
def _valid_output(text: Optional[str], min_len: int = MIN_OUTPUT_LENGTH) -> bool:
    if not text or len(text.strip()) < min_len:
        return False
    t_lower = text[:200].lower()
    bad_signals = ["i'm sorry", "i cannot", "i can't", "as an ai",  "error:", "exception", "traceback", "out of memory"]
    return not any(bad in t_lower for bad in bad_signals)

def _fallback(task: str) -> Tuple[str, str]:
    try:
        result = phi_generate(task)
        if _valid_output(result):
            _log("fallback_success", {"agent": "phi", "output_length": len(result)})
            return result, "phi"
    except Exception as e:
        _log("fallback_exception", {"agent": "phi", "error": str(e)})
    return "Unable to complete request. Please try rephrasing or breaking down the task.", "phi"

def _merge_results(code: Optional[str], text: Optional[str]) -> str:
    parts = []
    if code and code.strip():
        parts.append(f"-> Implementation\n{code.strip()}")
    if text and text.strip():
        parts.append(f"-> Explanation\n{text.strip()}")
    return "\n\n".join(parts) if parts else "No output generated.Try again later!"

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
    _log("task_received", {"task_preview": task_text[:100] + "..." if len(task_text) > 100 else task_text})
    try:
        classification = _classify(_build_classification_prompt(task_text))
        if not classification:
            classification = "text"
        _log("classified", {"classification": classification})
        models, need_split = _route_models(classification)
        if need_split:
            decomp_prompt = _build_decomposition_prompt(task_text)
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit( client.chat, model="llama3:8b", messages=[{"role": "user", "content": decomp_prompt}], options={"temperature": 0.0, "num_predict": 512, "top_p": 0.9}, keep_alive=0)
                    resp = future.result(timeout=CLASSIFICATION_TIMEOUT_SECONDS)
                    raw_content = _extract_content(resp).strip()
                    parsed = _parse_json_output(raw_content, expected_keys=["part_1", "part_2"])
                    if parsed:
                        code_task = parsed["part_2"].get("scope", parsed["part_2"].get("title", task_text))
                        text_task = parsed["part_1"].get("scope", parsed["part_1"].get("title", task_text))
                    else:
                        code_task = text_task = task_text
                        _log("decomposition_parse_failed", {"raw_preview": raw_content[:100]})
            except Exception as e:
                _log("decomposition_error", {"error": str(e)[:150]})
                code_task = text_task = task_text
        else:
            code_task = text_task = task_text
        _log("tasks_prepared", {"code_task_preview": code_task[:80] + "..." if len(code_task) > 80 else code_task,"text_task_preview": text_task[:80] + "..." if len(text_task) > 80 else text_task})
        results: Dict[str, str] = {}
        
        def _run_agent(agent_name: str, task: str) -> Tuple[str, str]:
            if agent_name == "deepseek":
                return deepseek_generate(task), "deepseek"
            elif agent_name == "mistral":
                return mistral_generate(task), "mistral"
            elif agent_name == "phi":
                return phi_generate(task), "phi"
            else:
                return _fallback(task)
        
        with ThreadPoolExecutor(max_workers=1) as ex:
            futures = {}
            if "deepseek" in models and code_task.strip():
                futures["code"] = ex.submit(_run_agent, "deepseek", code_task)
            if "mistral" in models and text_task.strip():
                futures["text"] = ex.submit(_run_agent, "mistral", text_task)
            for future in as_completed(futures.values(), timeout=AGENT_TIMEOUT_SECONDS):
                task_key = next((k for k, v in futures.items() if v == future), "unknown")
                try:
                    result, agent = future.result()
                    if not _valid_output(result):
                        _log("invalid_output", {"task": task_key, "agent": agent})
                        result, agent = _fallback(task_text)
                        fallback_used = True
                    else:
                        _log("agent_success", {"task": task_key, "agent": agent, "output_length": len(result)})
                    results[task_key] = result
                    if agent not in agent_trace:
                        agent_trace.append(agent)
                except Exception as e:
                    _log("agent_execution_error", {"task": task_key, "error": str(e)})
                    result, agent = _fallback(task_text)
                    results[task_key] = result
                    fallback_used = True
                    if agent not in agent_trace:
                        agent_trace.append(agent)
        final_output = _merge_results( results.get("code", ""), results.get("text", ""))
        _log("output_merged", {"length": len(final_output)})
        if use_quality_check and _gemini_quota.check():
            try:
                _gemini_quota.decrement()
                final_output = _quality_check(final_output, task_text)
                _log("quality_check_applied", {})
            except Exception as e:
                _gemini_quota.refund()
                _log("quality_check_failed", {"error": str(e)})
        return { "output": final_output, "agents_used": agent_trace, "classification": classification, "fallback_used": fallback_used, "gemini_quota_remaining": _gemini_quota.remaining, "success": True}
    except Exception as e:
        _log("orchestrator_crash", {"error": str(e), "type": type(e).__name__})
        fallback, agent = _fallback(task_text)
        return { "output": fallback, "agents_used": [agent], "classification": "error", "fallback_used": True, "error": str(e), "gemini_quota_remaining": _gemini_quota.remaining, "success": False}

def generate(task_text: str, use_quality_check: bool = False) -> Dict:
    return orchestrate(task_text, use_quality_check)