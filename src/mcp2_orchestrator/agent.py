import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Literal, cast

from openai import AsyncAzureOpenAI
from openai.types.chat import ChatCompletionToolParam
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)

from mcp2_orchestrator.mcp1_client import Mcp1Client
from mcp2_orchestrator.settings import settings

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

SYSTEM_PROMPT = """\
You are a research agent with access to a knowledge base about Acme Robotics.
You MUST only answer from retrieved information — never from prior knowledge.

You maintain a scratchpad of tasks to track your research progress.
Before doing anything, always consult the current scratchpad state in the system message.

Your workflow:
1. Decompose the question into tasks using `add_task`. Use `depends_on` when one task requires
   the result of another.
2. Execute tasks by calling `search_knowledge` to retrieve relevant documents.
3. Mark each task done with `complete_task` once you have retrieved useful results.
4. When all tasks needed to answer the question are complete, call `finish` with a synthesized answer.

Rules:
- Always use `search_knowledge` — never answer from memory.
- Call `finish` only when you have enough retrieved information to answer fully.
- If you hit a dead end on a task, mark it complete with a note and move on.
"""

# --- Tool schemas for OpenAI function calling ---

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the Acme Robotics knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (default 3)",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a new research task to the scratchpad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What this task will research",
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Task IDs this task must wait for",
                        "default": [],
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as complete and record its result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "ID of the task"},
                    "result": {
                        "type": "string",
                        "description": "Summary of what was found",
                    },
                },
                "required": ["task_id", "result"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Provide the final synthesized answer and end the research loop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "Final answer based on retrieved information",
                    }
                },
                "required": ["answer"],
            },
        },
    },
]


@dataclass
class Task:
    id: int
    description: str
    status: Literal["pending", "running", "complete", "blocked"] = "pending"
    depends_on: list[int] = field(default_factory=list)
    result: str | None = None


@dataclass
class Scratchpad:
    question: str
    tasks: list[Task] = field(default_factory=list)
    final_answer: str | None = None
    _next_id: int = 0

    def add_task(self, description: str, depends_on: list[int] | None = None) -> int:
        task_id = self._next_id
        self._next_id += 1
        self.tasks.append(
            Task(id=task_id, description=description, depends_on=depends_on or [])
        )
        return task_id

    def complete_task(self, task_id: int, result: str) -> None:
        for t in self.tasks:
            if t.id == task_id:
                t.status = "complete"
                t.result = result
                return

    def runnable_tasks(self) -> list[Task]:
        complete_ids = {t.id for t in self.tasks if t.status == "complete"}
        return [
            t
            for t in self.tasks
            if t.status == "pending" and set(t.depends_on).issubset(complete_ids)
        ]

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "tasks": [
                {
                    "id": t.id,
                    "description": t.description,
                    "status": t.status,
                    "depends_on": t.depends_on,
                    "result": t.result,
                }
                for t in self.tasks
            ],
            "final_answer": self.final_answer,
        }


class Agent:
    def __init__(self, mcp1: Mcp1Client):
        self._mcp1 = mcp1
        self._llm = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )

    async def run(self, question: str) -> str:
        logger.info("Agent starting — question: %r", question)
        scratchpad = Scratchpad(question=question)
        messages: list[dict] = []

        for iteration in range(MAX_ITERATIONS):
            logger.debug("Iteration %d", iteration)
            system_content = (
                SYSTEM_PROMPT
                + "\n\n--- Current Scratchpad ---\n"
                + json.dumps(scratchpad.to_dict(), indent=2)
            )

            response = await self._llm.chat.completions.create(
                model=settings.azure_chat_deployment,
                messages=[{"role": "system", "content": system_content}] + messages,
                tools=cast(list[ChatCompletionToolParam], TOOL_SCHEMAS),
                tool_choice="auto",
            )

            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_unset=False))

            # No tool calls → treat as implicit finish
            if not msg.tool_calls:
                if msg.content:
                    return msg.content
                break

            # Collect parallel search_knowledge calls, execute concurrently
            search_calls = []
            non_search_calls = []
            for tc in [
                tc
                for tc in msg.tool_calls
                if isinstance(tc, ChatCompletionMessageToolCall)
            ]:
                if tc.function.name == "search_knowledge":
                    search_calls.append(tc)
                else:
                    non_search_calls.append(tc)

            tool_results: list[dict] = []

            if search_calls:

                async def _search(tc):
                    args = json.loads(tc.function.arguments)
                    logger.info(
                        "Invoking tool: search_knowledge  query=%r  top_k=%s",
                        args["query"],
                        args.get("top_k", 3),
                    )
                    results = await self._mcp1.search(
                        query=args["query"], top_k=args.get("top_k", 3)
                    )
                    return {
                        "tool_call_id": tc.id,
                        "role": "tool",
                        "content": json.dumps(results),
                    }

                search_results = await asyncio.gather(
                    *[_search(tc) for tc in search_calls]
                )
                tool_results.extend(search_results)

            # Process non-search tool calls sequentially (they mutate scratchpad)
            done = False
            for tc in non_search_calls:
                args = json.loads(tc.function.arguments)
                fn = tc.function.name

                if fn == "add_task":
                    logger.info(
                        "Invoking tool: add_task  description=%r  depends_on=%s",
                        args["description"],
                        args.get("depends_on", []),
                    )
                    task_id = scratchpad.add_task(
                        description=args["description"],
                        depends_on=args.get("depends_on", []),
                    )
                    tool_results.append(
                        {
                            "tool_call_id": tc.id,
                            "role": "tool",
                            "content": json.dumps({"task_id": task_id}),
                        }
                    )

                elif fn == "complete_task":
                    logger.info(
                        "Invoking tool: complete_task  task_id=%s", args["task_id"]
                    )
                    scratchpad.complete_task(args["task_id"], args["result"])
                    tool_results.append(
                        {
                            "tool_call_id": tc.id,
                            "role": "tool",
                            "content": json.dumps({"status": "ok"}),
                        }
                    )

                elif fn == "finish":
                    logger.info("Invoking tool: finish")
                    scratchpad.final_answer = args["answer"]
                    tool_results.append(
                        {
                            "tool_call_id": tc.id,
                            "role": "tool",
                            "content": json.dumps({"status": "done"}),
                        }
                    )
                    done = True

            messages.extend(tool_results)

            if done:
                break

        if scratchpad.final_answer:
            return scratchpad.final_answer

        # Partial answer fallback
        completed = [t for t in scratchpad.tasks if t.status == "complete" and t.result]
        if completed:
            partial = "\n".join(f"- {t.description}: {t.result}" for t in completed)
            return f"[Partial answer — max iterations reached]\n{partial}"

        return "Unable to answer: no results retrieved within iteration limit."
