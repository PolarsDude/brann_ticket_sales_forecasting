"""LangGraph text-to-SQL agent for the Brann analytics database.

Run with: uv run python -m src.agent "How many points does Brann have?"
Set OPENAI_API_KEY before running.
"""
import json
import re
import sys
from typing import TypedDict

import duckdb
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from dotenv import load_dotenv

from src.config import DB_PATH, PROJECT_ROOT


GUIDE_PATH = PROJECT_ROOT / "AGENT_DATABASE_GUIDE.md"
ALLOWED_TABLES = {
    "dim_teams",
    "fct_matches",
    "fct_goal_scorers",
    "fct_league_standings",
}
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(attach|copy|create|delete|drop|export|insert|install|load|update|"
    r"pragma|replace|truncate|vacuum)\b",
    re.IGNORECASE,
)
MAX_TASKS = 4

load_dotenv(PROJECT_ROOT / ".env")


class AgentState(TypedDict):
    """Data passed between the LangGraph nodes."""

    question: str
    tasks: list[str]
    task_index: int
    generated_sqls: list[str]
    collected_results: list[dict[str, object]]
    current_task: str
    sql: str
    columns: list[str]
    rows: list[tuple]
    summary: str
    sql_error: str
    attempts: int


def plan_tasks(state: AgentState) -> dict[str, object]:
    """Split the user request into a small set of report tasks."""
    instructions = f"""You create an analysis plan for a DuckDB SQL agent.

Goal: split the user's request into 1-{MAX_TASKS} concrete, answerable tasks.

Rules:
- Keep tasks focused and non-overlapping.
- If one SQL query is enough, return exactly one task.
- Keep every task in Norwegian.
- Return ONLY valid JSON with this shape:
  {{"tasks": ["task 1", "task 2"]}}
"""
    model = ChatOpenAI(model="gpt-4.1", temperature=0)
    response = model.invoke(f"{instructions}\nBrukerspørsmål: {state['question']}")

    tasks: list[str]
    try:
        parsed = json.loads(str(response.content))
        raw_tasks = parsed.get("tasks", []) if isinstance(parsed, dict) else []
        tasks = [str(task).strip() for task in raw_tasks if str(task).strip()]
    except json.JSONDecodeError:
        tasks = []

    if not tasks:
        tasks = [state["question"]]

    tasks = tasks[:MAX_TASKS]
    return {
        "tasks": tasks,
        "task_index": 0,
        "generated_sqls": [],
        "collected_results": [],
        "current_task": tasks[0],
        "sql_error": "",
        "attempts": 0,
    }


def generate_sql(state: AgentState) -> dict[str, str]:
    """LangChain node that translates one task into one SQL query."""
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    instructions = f"""You translate questions about SK Brann into DuckDB SQL.

{guide}

Return only one SQL statement. It must start with SELECT or WITH, read only from
dim_teams, fct_matches, fct_goal_scorers, and/or fct_league_standings, and never use markdown fences or an explanation.

Always use 'SK Brann' for Brann. For every other team mentioned by the user, resolve
the name in a CTE from dim_teams with ILIKE before using it in a match or standings
filter. Never invent, guess, or use an external variant of a team name.
"""
    model = ChatOpenAI(model="gpt-4.1", temperature=0)
    error_feedback = ""
    if state.get("sql_error"):
        error_feedback = f"""\nThe previous SQL failed with this error:
{state['sql_error']}
Generate a corrected query that avoids the error.\n"""
    current_task = state["tasks"][state["task_index"]]
    response = model.invoke(
        f"{instructions}{error_feedback}\nQuestion: {current_task}"
    )
    sql = str(response.content)
    return {
        "current_task": current_task,
        "sql": sql.removeprefix("```sql").removeprefix("```").removesuffix("```").strip(),
        "attempts": state.get("attempts", 0) + 1,
    }


def validate_sql(sql: str) -> None:
    """Reject statements outside the small read-only analytics surface."""
    normalized = sql.strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", normalized, re.IGNORECASE):
        raise ValueError("Agenten returnerte ikke en SELECT/WITH-spørring.")
    if ";" in normalized or FORBIDDEN_KEYWORDS.search(normalized):
        raise ValueError("Agenten returnerte en ikke tillatt SQL-spørring.")

    referenced_tables = set(
        match.lower()
        for match in re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", normalized, re.IGNORECASE)
    )
    cte_names = set(
        match.lower()
        for match in re.findall(
            r"(?:\bwith|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(",
            normalized,
            re.IGNORECASE,
        )
    )
    if not referenced_tables or not referenced_tables.issubset(ALLOWED_TABLES | cte_names):
        raise ValueError("Spørringen bruker en tabell som agenten ikke har tilgang til.")


def execute_sql(state: AgentState) -> dict[str, object]:
    """LangGraph node that validates and executes the generated SQL."""
    try:
        validate_sql(state["sql"])

        with duckdb.connect(str(DB_PATH), read_only=True) as connection:
            result = connection.execute(state["sql"])
            columns = [column[0] for column in result.description]
            rows = result.fetchall()
    except (ValueError, duckdb.Error) as error:
        if state.get("attempts", 0) >= 2:
            raise RuntimeError(
                f"SQL-spørringen kunne ikke valideres eller kjøres etter to forsøk: {error}"
            ) from error
        return {"sql_error": str(error), "columns": [], "rows": []}

    return {"columns": columns, "rows": rows, "sql_error": ""}


def collect_result(state: AgentState) -> dict[str, object]:
    """Store one task result and advance to the next task."""
    collected_results = list(state.get("collected_results", []))
    generated_sqls = list(state.get("generated_sqls", []))
    limited_rows = state["rows"][:30]

    collected_results.append(
        {
            "task": state["current_task"],
            "sql": state["sql"],
            "columns": state["columns"],
            "rows": limited_rows,
            "truncated": len(state["rows"]) > len(limited_rows),
        }
    )
    generated_sqls.append(state["sql"])

    next_index = state["task_index"] + 1
    next_task = state["tasks"][next_index] if next_index < len(state["tasks"]) else ""
    return {
        "collected_results": collected_results,
        "generated_sqls": generated_sqls,
        "task_index": next_index,
        "current_task": next_task,
        "sql_error": "",
        "attempts": 0,
    }


def summarize_results(state: AgentState) -> dict[str, str]:
    """Turn all task results into one concise report."""
    if not state.get("collected_results"):
        return {"summary": "Jeg fant ingen resultater for spørsmålet."}

    blocks: list[str] = []
    for index, result in enumerate(state["collected_results"], start=1):
        columns = result.get("columns", [])
        rows = result.get("rows", [])
        columns_text = ", ".join(columns) if isinstance(columns, list) else ""
        row_lines = "\n".join(str(row) for row in rows)
        truncated_note = "\n[Resultatet er avkortet til de første 30 radene.]" if result.get("truncated") else ""
        blocks.append(
            f"Del {index}: {result.get('task', '')}\n"
            f"SQL: {result.get('sql', '')}\n"
            f"Kolonner: {columns_text}\n"
            f"Rader:\n{row_lines if row_lines else '[Ingen rader]'}{truncated_note}"
        )

    result_text = "\n\n".join(blocks)
    instructions = f"""Svar kort på norsk på brukerens spørsmål.
Skriv en kort rapport i vanlig tekst, ikke som tabell.
Strukturer rapporten med en kort innledning, 2-4 funn og en kort konklusjon.
Ikke gjett eller legg til informasjon som ikke finnes i resultatet.
Spørsmål: {state['question']}

SQL-resultat:
{result_text}
"""
    model = ChatOpenAI(model="gpt-4.1", temperature=0)
    response = model.invoke(instructions)
    return {"summary": str(response.content).strip()}


workflow = StateGraph(AgentState)
workflow.add_node("plan_tasks", plan_tasks)
workflow.add_node("generate_sql", generate_sql)
workflow.add_node("execute_sql", execute_sql)
workflow.add_node("collect_result", collect_result)
workflow.add_node("summarize_results", summarize_results)
workflow.add_edge(START, "plan_tasks")
workflow.add_edge("plan_tasks", "generate_sql")
workflow.add_edge("generate_sql", "execute_sql")


def route_after_execution(state: AgentState) -> str:
    """Retry failed SQL once; otherwise continue to the answer step."""
    return "generate_sql" if state.get("sql_error") else "collect_result"


def route_after_collection(state: AgentState) -> str:
    """Continue with the next task or finish with a summary."""
    return "generate_sql" if state["task_index"] < len(state["tasks"]) else "summarize_results"


workflow.add_conditional_edges(
    "execute_sql",
    route_after_execution,
    {"generate_sql": "generate_sql", "collect_result": "collect_result"},
)
workflow.add_conditional_edges(
    "collect_result",
    route_after_collection,
    {"generate_sql": "generate_sql", "summarize_results": "summarize_results"},
)
workflow.add_edge("summarize_results", END)
agent = workflow.compile()


def run_question(question: str) -> None:
    result = agent.invoke({"question": question})

    sqls = result.get("generated_sqls") or [result.get("sql", "")]
    for index, sql in enumerate(sqls, start=1):
        print(f"SQL {index}:\n{sql}\n")
    print("\nSammendrag:\n" + result["summary"])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('Bruk: uv run python -m src.agent "Hvor mange poeng har Brann?"')
    run_question(" ".join(sys.argv[1:]))