from ollama import Client
import logging
import json
import time
import re
from typing import Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

client = Client()
logger = logging.getLogger("learn_orchestra")

AGENT_CAPABILITIES = {
    "phi3:mini":["syllabus_analyzer", "formatter", "viva", "general"],
    "qwen2.5-coder:3b":["coding_questions", "code_examples"],
    "llama3:8b-instruct-q4_K_M":["theory_lecture", "notes", "progressive"],
}

MODEL_DEVICE = {
    "phi3:mini":0,
    "qwen2.5-coder:3b":0,
    "llama3:8b-instruct-q4_K_M":99,
}

DECOMPOSER_MODEL = "phi3:mini"
MERGER_MODEL     = "llama3:8b-instruct-q4_K_M"

OUTPUT_TYPES = ["qp", "viva", "theory_lecture", "notes", "progressive", "resources"]
CS_SUBJECTS  = ["python", "java", "javascript", "c", "c++", "data structures","algorithms", "dbms", "os", "networks", "web", "react", "sql"]

_JSON_ARRAY_RE  = re.compile(r'\[\s*\{.*?\}\s*\]', re.DOTALL)
_JSON_OBJECT_RE = re.compile(r'\{.*?\}', re.DOTALL)


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


def _detect_intent(task: str) -> Dict:
    prompt = f"""You are an intent classifier for a CS learning platform.

        Given the user input below, extract:
        1. "subject": what subject/language is the syllabus about? (e.g. "python", "java", "math", "data structures")
        2. "output_type": what does the user want? One of: {OUTPUT_TYPES}
        3. "is_cs": true if the subject is CS/programming related, false if it's math or unrelated
        4. "difficulty": "beginner", "intermediate", or "advanced" based on context clues

        OUTPUT ONLY a valid JSON object, no explanation, no markdown.

        OUTPUT FORMAT:
        {{"subject": "python", "output_type": "qp", "is_cs": true, "difficulty": "intermediate"}}

        USER INPUT:
        {task}"""

    try:
        response = client.chat( model=DECOMPOSER_MODEL, messages=[{"role": "user", "content": prompt}], options={"temperature": 0.0, "num_predict": 100, "num_gpu": MODEL_DEVICE.get(DECOMPOSER_MODEL, 0)}, keep_alive=30,)
        raw = _extract_content(response).strip()
        match = _JSON_OBJECT_RE.search(raw)
        if match:
            data = json.loads(match.group())
            _log("INTENT_DETECTED", data)
            return data
    except Exception as e:
        _log("INTENT_ERROR", {"error": str(e)})
    return {"subject": "general", "output_type": "qp", "is_cs": True, "difficulty": "intermediate"}

def _decompose(task: str, intent: Dict) -> List[Dict]:
    output_type = intent.get("output_type", "qp")
    subject = intent.get("subject", "general")
    difficulty  = intent.get("difficulty", "intermediate")

    type_map = {
        "qp":["coding_questions", "theory_lecture", "formatter"],
        "viva":["viva", "code_examples", "formatter"],
        "theory_lecture":["theory_lecture", "notes", "formatter"],
        "notes":["notes", "code_examples", "formatter"],
        "progressive":["progressive", "coding_questions", "formatter"],
        "resources":["general", "formatter"],
    }
    subtask_types = type_map.get(output_type, ["general", "formatter"])
    prompt = f"""You are a learning content architect.

            A user has uploaded a {subject} syllabus and wants: {output_type}
            Difficulty level: {difficulty}

            Break this into independent subtasks for different agents to work on in parallel.

            SYLLABUS/TASK:
            {task}

            RULES:
            - Return ONLY a valid JSON array, no explanation, no markdown
            - Each item must have:
              - "id": unique string (e.g. "s1", "s2")
              - "type": one of {subtask_types}
              - "description": exactly what to generate for this subtask (be specific about topics)
            - Minimum 2 subtasks, maximum 5
            - Every subtask must be independently completable

            OUTPUT FORMAT:
            [
              {{"id": "s1", "type": "{subtask_types[0]}", "description": "Generate questions on topic X covering Y"}},
              {{"id": "s2", "type": "{subtask_types[1]}", "description": "Write theory notes on topic Z"}}
            ]"""

    try:
        response = client.chat( model=DECOMPOSER_MODEL, messages=[{"role": "user", "content": prompt}], options={"temperature": 0.1, "num_predict": 1200, "num_gpu": MODEL_DEVICE.get(DECOMPOSER_MODEL, 0)}, keep_alive=30,)
        text = _extract_content(response)
        plan = _parse_json_safely(text)
        if isinstance(plan, list) and len(plan) >= 2:
            _log("DECOMPOSE_SUCCESS", {"subtasks": len(plan)})
            return plan
        _log("DECOMPOSE_FALLBACK", {})
    except Exception as e:
        _log("DECOMPOSE_ERROR", {"error": str(e)})
    return _fallback_plan(task, output_type, subject)


def _fallback_plan(task: str, output_type: str, subject: str) -> List[Dict]:
    return [
        {"id": "s1", "type": "coding_questions",  "description": f"Generate {output_type} questions for {subject}: {task[:100]}"},
        {"id": "s2", "type": "theory_lecture",    "description": f"Write theory content for {subject}: {task[:100]}"},
        {"id": "s3", "type": "formatter",         "description": f"Format the final {output_type} document for {subject}"},
    ]


TYPE_INSTRUCTIONS = {
    "coding_questions": """Generate clear, well-structured coding questions.
        Include: problem statement, sample input/output, constraints.
        Mix easy, medium and hard questions. Return ONLY the questions, no solutions.""",

    "theory_lecture": """Write comprehensive theory notes or lecture content.
        Include: concepts, definitions, examples, key points.
        Use clear headings and structure. Return ONLY the content.""",

    "notes": """Write concise study notes with bullet points.
        Cover key concepts, formulas, and important points.
        Return ONLY the notes.""",

    "viva": """Generate viva voce questions with expected answers.
        Mix conceptual, practical and tricky questions.
        Format: Q: ... A: ...
        Return ONLY the questions and answers.""",

    "progressive": """Generate questions in progressive difficulty order.
        Start from absolute basics (level 1) → intermediate (level 2) → advanced (level 3).
        Label each question with its level.
        Return ONLY the questions.""",

    "code_examples": """Write clean, well-commented code examples.
        Show practical usage of the concept.
        Return ONLY the code with inline comments.""",

    "formatter": """Format the content into a clean, professional document structure.
        Add proper headings, sections, numbering.
        Return ONLY the formatted document.""",

    "general": """Generate helpful learning content for this topic.
        Include key concepts, examples and study tips.
        Return ONLY the content.""",
}


def _build_subtask(model: str, subtask: Dict, context: str, intent: Dict) -> Dict:
    instruction = TYPE_INSTRUCTIONS.get(subtask["type"], TYPE_INSTRUCTIONS["general"])
    subject     = intent.get("subject", "general")
    difficulty  = intent.get("difficulty", "intermediate")
    prompt = f"""You are an expert {subject} educator creating learning content.

            Difficulty level: {difficulty}
            Subject: {subject}

            Context (full syllabus/task):
            {context}

            Your specific task:
            {subtask['description']}

            Instructions:
            {instruction}"""

    try:
        response = client.chat(model=model,messages=[{"role": "user", "content": prompt}],options={"temperature": 0.2, "num_predict": 1500, "num_gpu": MODEL_DEVICE.get(model, 0)},keep_alive=30,)
        content = _extract_content(response)
        _log("SUBTASK_DONE", {"id": subtask["id"], "model": model, "type": subtask["type"]})
        return {"id": subtask["id"], "type": subtask["type"], "content": content, "error": None}
    except Exception as e:
        _log("SUBTASK_ERROR", {"id": subtask["id"], "error": str(e)})
        return {"id": subtask["id"], "type": subtask["type"], "content": "", "error": str(e)}


def _merge(task: str, results: List[Dict], intent: Dict) -> str:
    output_type = intent.get("output_type", "qp")
    subject     = intent.get("subject", "general")
    difficulty  = intent.get("difficulty", "intermediate")
    parts = []
    for r in results:
        if r["content"]:
            parts.append(f"--- [{r['type'].upper()}] ---\n{r['content']}")
    combined = "\n\n".join(parts)
    prompt = f"""You are a senior {subject} educator and content designer.

            You have received independently generated learning content pieces.

            Original request: {task}
            Output type: {output_type}
            Subject: {subject}
            Difficulty: {difficulty}

            Content pieces:
            {combined}

            Your job:
            - Merge all pieces into one clean, professional {output_type} document
            - Remove duplicates and conflicts
            - Ensure logical flow and proper structure
            - Add clear section headings and numbering
            - Make it ready to use as-is

            STRICT RULES:
            - If output_type is "qp": format as a proper question paper with sections, marks, time limit
            - If output_type is "viva": format as numbered Q&A pairs
            - If output_type is "progressive": clearly label difficulty levels
            - If output_type is "theory_lecture": format as structured lecture notes
            - Return ONLY the final document, no meta-commentary"""

    try:
        response = client.chat(model=MERGER_MODEL,messages=[{"role": "user", "content": prompt}],options={"temperature": 0.1, "num_predict": 2500, "num_gpu": MODEL_DEVICE.get(MERGER_MODEL, 0)},keep_alive=0,)
        _log("MERGE_DONE", {})
        return _extract_content(response)
    except Exception as e:
        _log("MERGE_ERROR", {"error": str(e)})
        return combined

def learn_pipeline(task: str) -> str:
    _log("PIPELINE_START", {"task_preview": task[:80]})
    intent = _detect_intent(task)
    subject = intent.get("subject", "general")
    math_warning = ""
    if not intent.get("is_cs", True):
        math_warning = f"⚠️ Note: This platform is optimized for CS/programming subjects. Results for '{subject}' may be limited.\n\n"
        _log("NON_CS_SUBJECT", {"subject": subject})

    plan = _decompose(task, intent)
    assignments = [(subtask, _assign_agent(subtask["type"])) for subtask in plan]
    _log("ASSIGNMENTS", {"units": [(a[0]["id"], a[1]) for a in assignments]})
    max_workers = min(len(assignments), 3)
    results: List[Dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = { executor.submit(_build_subtask, model, subtask, task, intent): subtask["id"] for subtask, model in assignments }
        for future in as_completed(futures):
            results.append(future.result())
    _log("ALL_SUBTASKS_DONE", {"count": len(results)})
    final = _merge(task, results, intent)
    _log("PIPELINE_DONE", {})
    return math_warning + final