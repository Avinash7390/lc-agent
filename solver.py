import random

from llm_client import chat_completion
from util import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT_CORRECT = """You are an expert competitive programmer. You solve LeetCode problems efficiently.

Rules:
- Write a complete solution in the requested language that can be directly submitted to LeetCode.
- Complete the provided LeetCode starter code snippet and preserve the exact class and method signature.
- Do NOT include any test code, main block, or print statements.
- Do NOT include any explanation or comments — just the pure solution code.
- Optimize for both correctness and performance.
- Use only the language standard library.
- Handle edge cases properly.
"""

SYSTEM_PROMPT_FLAWED = """You are simulating a programmer who is attempting a LeetCode problem but makes a mistake.
Your solution should look like a genuine human attempt — structurally reasonable but with a subtle bug.

Rules:
- Write a complete solution in the requested language using the exact provided LeetCode starter signature.
- Do NOT include any test code, main block, or print statements.
- Do NOT include any explanation or comments — just the pure solution code.
- The solution MUST have exactly ONE subtle bug that causes it to fail on some test cases.
- The bug should be realistic — something a human would actually do wrong, such as:
  - Off-by-one error in a loop boundary
  - Wrong comparison operator (< instead of <=)
  - Forgetting to handle an edge case (empty array, single element, negative numbers)
  - Incorrect base case in recursion
  - Using the wrong variable in a calculation
  - Not sorting when needed, or sorting in wrong order
  - Integer overflow not handled
- The overall approach/algorithm should be CORRECT — only introduce a small implementation bug.
- Do NOT make it obviously wrong (no syntax errors, no completely broken logic).
- It should pass some test cases but fail on others.
"""

SYSTEM_PROMPT_IMPROVE = """You are simulating a programmer who got a Wrong Answer on their previous attempt and is now fixing their solution.
You previously submitted a solution that had a bug. Now you're improving it.

Rules:
- Write a complete solution in the requested language using the exact provided LeetCode starter signature.
- Do NOT include any test code, main block, or print statements.
- Do NOT include any explanation or comments — just the pure solution code.
- Based on the previous attempt and the error, provide an IMPROVED solution.
- Whether this solution is fully correct depends on the attempt number:
  - If this is attempt 2 of 3: the solution might still have a minor issue (50/50 chance), or it could be correct.
  - If this is the final attempt: the solution MUST be fully correct.
- Use only the language standard library.
"""


def solve_problem(potd, language="cpp"):
    """
    Generates the correct solution for the problem.
    Called once — the correct solution is cached and used on the final attempt.
    """
    user_prompt = _build_problem_prompt(potd, language)
    user_prompt += "\n\nReturn ONLY the complete Solution class code, nothing else."

    logger.info(f"Before LLM call: generating correct solution for {potd.get('title', 'N/A')!r} in {_language_label(language)}")

    response = chat_completion(SYSTEM_PROMPT_CORRECT, user_prompt)
    logger.info("After LLM call: correct solution response received")
    solution = extract_code(response)

    logger.info(f"Correct solution extracted ({len(solution)} chars)")
    return solution


def _language_label(language):
    labels = {
        "cpp": "C++",
        "python3": "Python 3",
        "java": "Java",
        "javascript": "JavaScript",
    }
    return labels.get((language or "cpp").lower(), language)


def _build_problem_prompt(potd, language="cpp"):
    """Build a comprehensive problem prompt including examples, constraints, and starter code."""
    starter_code = potd.get("starter_code") or ""
    parts = [
        f"Language: {_language_label(language)}",
        f"Title: {potd.get('title', '')}",
        f"Difficulty: {potd.get('difficulty', '')}",
        f"\nProblem:\n{potd.get('content_text', '')}",
    ]

    if starter_code:
        parts.extend([
            "\nLeetCode starter code to complete:",
            f"```{language}\n{starter_code}\n```",
        ])
    else:
        logger.warning("No LeetCode starter code snippet was available for the selected language")

    if potd.get("examples"):
        parts.append("\nExamples:")
        for i, example in enumerate(potd["examples"], 1):
            parts.append(f"  Example {i}: {example}")

    if potd.get("constraints"):
        parts.append("\nConstraints:")
        for constraint in potd["constraints"]:
            parts.append(f"  • {constraint}")

    if potd.get("follow_up"):
        parts.append(f"\nFollow-up (expected complexity): {potd['follow_up']}")

    return "\n".join(parts)

def generate_flawed_solution(potd, attempt_number, previous_solution=None, language="cpp"):
    """
    Generates a deliberately flawed solution that mimics a human's first/early attempt.
    """
    problem_context = _build_problem_prompt(potd, language)

    if attempt_number == 1:
        system = SYSTEM_PROMPT_FLAWED
        user_prompt = f"""Solve this LeetCode problem in {_language_label(language)}, but make ONE subtle bug:

{problem_context}

Return ONLY the complete Solution class code with the subtle bug. No explanations."""
    else:
        system = SYSTEM_PROMPT_IMPROVE
        user_prompt = f"""Fix this LeetCode solution that got Wrong Answer:

{problem_context}

Previous (buggy) attempt:
```{language}
{previous_solution}
```

Provide an improved solution. This is attempt {attempt_number}.
Return ONLY the complete Solution class code, nothing else."""

    logger.info(f"Before LLM call: generating flawed/improved solution for attempt {attempt_number}")

    response = chat_completion(system, user_prompt)
    logger.info(f"After LLM call: attempt {attempt_number} solution response received")
    solution = extract_code(response)

    logger.info(f"Attempt {attempt_number} solution extracted ({len(solution)} chars)")
    return solution



def solve_problem_with_feedback(potd, previous_solution, previous_result, language="cpp"):
    """Generate a corrected solution after a failed supposedly-correct attempt."""
    problem_context = _build_problem_prompt(potd, language)
    status = (previous_result or {}).get("status", "Unknown")
    details = (previous_result or {}).get("details", "")
    user_prompt = f"""The previous solution failed on LeetCode. You must fix it.

Failure reason from LeetCode:
- Status: {status}
- Details: {details}

Use the failure reason to identify the bug. Pay close attention to the failed testcase, expected behavior, edge cases, method signature, and constraints.

{problem_context}

Previous failed solution:
```{language}
{previous_solution}
```

Return ONLY a corrected complete Solution class in {_language_label(language)}. No explanation."""

    logger.info(
        f"Before LLM call: correcting solution for {potd.get('title', 'N/A')!r} "
        f"after status={status!r}"
    )
    response = chat_completion(SYSTEM_PROMPT_CORRECT, user_prompt)
    logger.info("After LLM call: corrected solution response received")
    solution = extract_code(response)
    logger.info(f"Corrected solution extracted ({len(solution)} chars)")
    return solution

def decide_attempt_strategy(max_attempts=3):
    """
    Decides which attempt will be the "correct" one.
    Simulates human-like behavior where probability of success increases with each attempt.

    Probability distribution (increasing — humans improve over time):
      - Attempt 1: 30% chance of getting it right in one go
      - Attempt 2: 60% chance of getting it right (after seeing the error)
      - Attempt 3: 100% (guaranteed — humans eventually figure it out)

    Returns the attempt number (1-indexed) on which to submit the correct solution.
    """
    probabilities = [1.00, 1.00, 1.00]

    for attempt_idx, prob in enumerate(probabilities[:max_attempts]):
        if random.random() < prob:
            return attempt_idx + 1

    return max_attempts


def extract_code(text):
    """Extract Python code from a response that might be wrapped in markdown code blocks."""
    if "```" in text:
        lines = text.split("\n")
        code_lines = []
        in_block = False

        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            elif line.strip() == "```" and in_block:
                in_block = False
                continue
            elif in_block:
                code_lines.append(line)

        return "\n".join(code_lines)

    return text.strip()
