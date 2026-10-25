"""A2A AgentExecutor: maps Sportscanner Agent onto the A2A task lifecycle.

submitted -> working -> completed (answer + court data artifacts)
                     -> input-required (agent asked a clarifying question)
                     -> failed (LLM unavailable, with a caller-safe reason)
"""

import json

from a2a.helpers import new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater

from sportscanner.agents.a2a.agent import CourtFinderAgent
from sportscanner.agents.a2a.llm import LLMError
from sportscanner.logger import logging


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))


class CourtFinderExecutor(AgentExecutor):
    def __init__(self, agent: CourtFinderAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        def say(text: str):
            return updater.new_agent_message([new_text_part(text)])

        user_text = context.get_user_input().strip()
        if not user_text:
            await updater.reject(say("Send a text message, e.g. 'badminton near E1 2AD tomorrow evening'."))
            return

        await updater.start_work(say("Checking live court availability across London…"))
        # Memory is keyed per caller as well as per context, so one caller
        # can't read another's conversation by reusing a contextId.
        caller = context.call_context.user.user_name if context.call_context else ""
        try:
            reply = await self.agent.respond(user_text, context_id=f"{caller}:{task.context_id}")
        except LLMError as exc:
            logging.error(f"A2A Sportscanner Agent LLM error: {exc}")
            await updater.failed(say(exc.public_message))
            return

        if reply.needs_input:
            await updater.requires_input(say(reply.text))
            return

        await updater.add_artifact([new_text_part(reply.text, media_type="text/plain")], name="answer")
        if reply.search_results:
            await updater.add_artifact(
                [new_data_part(_json_safe(reply.search_results), media_type="application/json")],
                name="court_availability",
            )
        await updater.complete(say(reply.text))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        await TaskUpdater(event_queue, task.id, task.context_id).cancel()
