from ollama import Client
import logging
import json
import time
import re
from typing import Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

client = Client()
logger = logging.getLogger("website_orchester")

AGENT_CAPABILITIES = {
    "deepseek-coder:1.3b":["backend", "api_integration"],
    "qwen2.5-coder:3b":["backend", "api_integration"],
    "starcoder2:3b":["react", "html_css"],
    "phi3:mini":["react", "html_css", "js_logic"],
}
MODEL_DEVICE = {
    "deepseek-coder:1.3b": 99,
    "starcoder2:3b":99,
    "qwen2.5-coder:3b":0,
    "phi3:mini":0,
}

DECOMPOSER_MODEL = "phi3:mini"
MERGER_MODEL="llama3:8b-instruct-q4_K_M"
_JSON_ARRAY_RE = re.compile(r'\[\s*\{.*?\}\s*\]', re.DOTALL)


def _log(event: str, data: Optional[Dict] = None):
    if not logger.isEnabledFor(logging.INFO):
        return
    data = data or {}
    data["_ts"] = round(time.time() % 10000, 2)
    payload = json.dumps(data, ensure_ascii=False, default=str)
    logger.info("%s | %s", event, payload)
    print(f"[LEARN_LOG] {event} | {payload}")

def _extract_content(response) -> str:
    if isinstance(response, dict):
        return response.get("content") or response.get("message", {}).get("content", "")
    msg = getattr(response, "message", None)
    return getattr(msg, "content", "") if msg else ""

def _parse_json_safely(text: str) -> Optional[List]:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        match = _JSON_ARRAY_RE.search(text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    _log("JSON_PARSE_FAILED", {"snippet": text[:200]})
    return None

def _assign_agent(subtask_type: str) -> str:
    for model, capabilities in AGENT_CAPABILITIES.items():
        if subtask_type in capabilities:
            return model
    return DECOMPOSER_MODEL

def _fallback_plan(task: str) -> List[Dict]:
    return [
        {"id": "s1", "type": "html_css",  "description": f"Build the HTML structure and CSS styling for: {task}"},
        {"id": "s2", "type": "react",     "description": f"Build React components for: {task}"},
        {"id": "s3", "type": "js_logic",  "description": f"Implement JS interactivity for: {task}"},
        {"id": "s4", "type": "backend",   "description": f"Build backend API routes for: {task}"},
    ]

def decompose(task: str) -> List[Dict]:
    prompt = f"""You are a senior full-stack architect.

        A user wants to build a website feature. Break it into independent coding subtasks.

        TASK:
        {task}

        RULES:
        - Return ONLY a valid JSON array, no explanation, no markdown
        - Each item must have:
          - "id": unique string (e.g. "s1", "s2")
          - "type": one of ["html_css", "react", "js_logic", "backend", "api_integration"]
          - "description": exactly what code to write for this subtask
        - Minimum 3 subtasks, maximum 6
        - Every subtask must be independently buildable
        - If the task is React-based, use ONLY "react" type — never pair "react" with "js_logic"  # ← add this

        OUTPUT FORMAT:
        [
          {{"id": "s1", "type": "react", "description": "Build a navbar with logo and nav links"}},
          {{"id": "s2", "type": "backend", "description": "Create /api/products GET route returning JSON list"}}
        ]"""
    try:
        response = client.chat(model=DECOMPOSER_MODEL,messages=[{"role": "user", "content": prompt}],options={"temperature": 0.1, "num_predict": 1200,"num_gpu": MODEL_DEVICE.get(DECOMPOSER_MODEL, 0)},keep_alive=0,)
        text = _extract_content(response)
        plan = _parse_json_safely(text)
        if isinstance(plan, list) and len(plan) >= 2:
            _log("DECOMPOSE_SUCCESS", {"subtasks": len(plan)})
            return plan
        _log("DECOMPOSE_FALLBACK", {})
        return _fallback_plan(task)
    except Exception as e:
        _log("DECOMPOSE_ERROR", {"error": str(e)})
        return _fallback_plan(task)

def _build_subtask(model: str, subtask: Dict, task_context: str) -> Dict:
    type_instructions = {
        "html_css":        "Write clean semantic HTML with embedded CSS. No JS. No React.",
        "react":           "Write a complete React functional component with hooks. Use inline styles or Tailwind. NO separate JS files. NO vanilla DOM manipulation. Everything self-contained in one component.",
        "js_logic":        "Write vanilla JavaScript only. No React, no imports. Pure functions only.",
        "backend":         "Write FastAPI route(s) with proper models and response schemas.",
        "api_integration": "Write the fetch/axios call with async/await, error handling, and typed response parsing.",
    }
    instruction = type_instructions.get(subtask["type"], "Write the code for this subtask.")
    prompt = f"""You are an expert {subtask['type']} developer.

            Overall project context:
            {task_context}

            Your specific subtask:
            {subtask['description']}

            Instructions:
            {instruction}

            Return ONLY the code. No explanation. No markdown fences."""
    try:
        response = client.chat( model=model, messages=[{"role": "user", "content": prompt}], options={"temperature": 0.15, "num_predict": 1200, "num_gpu": MODEL_DEVICE.get(model, 0)}, keep_alive=0,)
        code = _extract_content(response)
        _log("SUBTASK_DONE", {"id": subtask["id"], "model": model})
        return {"id": subtask["id"], "type": subtask["type"], "code": code, "error": None}

    except Exception as e:
        _log("SUBTASK_ERROR", {"id": subtask["id"], "error": str(e)})
        return {"id": subtask["id"], "type": subtask["type"], "code": "", "error": str(e)}


def _merge(task: str, subtask_results: List[Dict]) -> str:
    parts = []
    for r in subtask_results:
        if r["code"]:parts.append(f"--- [{r['type'].upper()}] ---\n{r['code']}")
    combined = "\n\n".join(parts)
    prompt = f"""You are a senior full-stack developer.

        You have received independently written code pieces for a website project.

        Original task:
        {task}

        Code pieces:
        {combined}

        Your job:
        - Stitch all pieces into one coherent, working codebase
        - Resolve any naming conflicts or duplications
        - Ensure frontend and backend are properly connected
        - Return ONLY the final unified code, no explanation
        
        STRICT RULES:
        - Remove incomplete or broken code
        - Ensure all imports are valid
        - Ensure backend and frontend API routes match EXACTLY
        - Return a working project
        - If something is broken, FIX it
        """

    try:
        response = client.chat( model=MERGER_MODEL, messages=[{"role": "user", "content": prompt}], options={"temperature": 0.1, "num_predict": 2000, "num_gpu": MODEL_DEVICE.get(MERGER_MODEL, 0)}, keep_alive=0,)
        _log("MERGE_DONE", {})
        return _extract_content(response)
    except Exception as e:
        _log("MERGE_ERROR", {"error": str(e)})
        return combined

def multi_agents(task: str) -> str:

    _log("PIPELINE_START", {"task_preview": task[:80]})
    plan = decompose(task)
    assignments = [(subtask, _assign_agent(subtask["type"])) for subtask in plan]
    _log("ASSIGNMENTS", {"units": [(a[0]["id"], a[1]) for a in assignments]})
    max_workers = min(len(assignments), 3)
    results: List[Dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_build_subtask, model, subtask, task): subtask["id"]for subtask, model in assignments}
        for future in as_completed(futures):
            results.append(future.result())
    _log("ALL_SUBTASKS_DONE", {"count": len(results)})
    final = _merge(task, results)
    _log("PIPELINE_DONE", {})
    return final