"""LangGraph text-to-SQL agent for the Brann analytics database.

Run with: uv run python src/agent.py "How many points does Brann have?"
Set OPENAI_API_KEY before running.
"""
import re
import sys
from typing import TypedDict

import duckdb
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from dotenv import load_dotenv

from src.config import DB_PATH, PROJECT_ROOT


GUIDE_PATH = PROJECT_ROOT / "AGENT_DATABASE_GUIDE.md"
ALLOWED_TABLES = {"dim_teams", "fct_matches", "fct_league_standings"}
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(attach|copy|create|delete|drop|export|insert|install|load|update|"
    r"pragma|replace|truncate|vacuum)\b",
    re.IGNORECASE,
)

load_dotenv(PROJECT_ROOT / ".env")


class AgentState(TypedDict):
    """Data passed between the LangGraph nodes."""

    question: str
    sql: str
    columns: list[str]
    rows: list[tuple]


def generate_sql(state: AgentState) -> dict[str, str]:
    """LangChain node that translates the question into one SQL query."""
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    instructions = f"""You translate questions about SK Brann into DuckDB SQL.

{guide}

Return only one SQL statement. It must start with SELECT or WITH, read only from
dim_teams, fct_matches, and/or fct_league_standings, and never use markdown fences or an explanation.

Always use 'SK Brann' for Brann. For every other team mentioned by the user, resolve
the name in a CTE from dim_teams with ILIKE before using it in a match or standings
filter. Never invent, guess, or use an external variant of a team name.
"""
    model = ChatOpenAI(model="gpt-4.1-mini", temperature=0)
    response = model.invoke(f"{instructions}\n\nQuestion: {state['question']}")
    sql = str(response.content)
    return {"sql": sql.removeprefix("```sql").removeprefix("```").removesuffix("```").strip()}


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


def execute_sql(state: AgentState) -> dict[str, list]:
    """LangGraph node that validates and executes the generated SQL."""
    validate_sql(state["sql"])

    with duckdb.connect(str(DB_PATH), read_only=True) as connection:
        result = connection.execute(state["sql"])
        columns = [column[0] for column in result.description]
        rows = result.fetchall()

    return {"columns": columns, "rows": rows}


workflow = StateGraph(AgentState)
workflow.add_node("generate_sql", generate_sql)
workflow.add_node("execute_sql", execute_sql)
workflow.add_edge(START, "generate_sql")
workflow.add_edge("generate_sql", "execute_sql")
workflow.add_edge("execute_sql", END)
agent = workflow.compile()


def run_question(question: str) -> None:
    result = agent.invoke({"question": question})

    print("SQL:\n" + result["sql"])
    print("\nResultat:")
    print(" | ".join(result["columns"]))
    for row in result["rows"]:
        print(" | ".join(str(value) for value in row))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('Bruk: uv run python src/agent.py "Hvor mange poeng har Brann?"')
    run_question(" ".join(sys.argv[1:]))