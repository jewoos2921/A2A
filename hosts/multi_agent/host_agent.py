import sys
import asyncio
import json
import functools
import uuid
import threading
from typing import List, Optional, Callable

from google.genai import types
import base64

from google.adk import Agent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.tool_context import ToolContext
from .remote_agent_connection import RemoteAgentConnections, TaskUpdateCallback

from common.client import A2ACardResolver
from common.types import (
    AgentCard,
    Message, TaskState, Task, TaskSendParams,
    TextPart, DataPart, Part, TaskStatusUpdateEvent
)


def convert_part(part: Part, tool_context: ToolContext):
    if part.type == 'text':
        return part.text
    elif part.type == 'data':
        return part.data

    elif part.type == 'file':
        file_id = part.file.name
        file_bytes = base64.b64decode(part.file.bytes)
        file_part = types.Part(
            inline_data=types.Blob(
                mime_type=part.file.mime_type,
                data=file_bytes))
        tool_context.save_artifact(file_id, file_part)
        tool_context.actions.skip_summarization = True
        tool_context.actions.escalate = True
        return DataPart(data={"artifact-file-id": file_id})
    return f"Unknown type: {part.type}"


def convert_parts(parts: list[Part], tool_context: ToolContext):
    rval = []
    for p in parts:
        rval.append(convert_part(p, tool_context))
    return rval


class HostAgent:
    def __init__(self,
                 remote_agent_addresses: List[str],
                 task_callback: TaskUpdateCallback | None = None):
        self.task_callback = task_callback
        self.remote_agent_connections: dict[str, RemoteAgentConnections] = {}
        self.cards: dict[str, AgentCard] = {}

        for address in remote_agent_addresses:
            card_resolver = A2ACardResolver(address)
            card = card_resolver.get_agent_card()
            remote_connection = RemoteAgentConnections(card)
            self.remote_agent_connections[card.name] = remote_connection
            self.cards[card.name] = card
        agent_info = []
        for ra in self.list_remote_agents():
            agent_info.append(json.dumps(ra))
        self.agents = '\n'.join(agent_info)

    def create_agent(self) -> Agent:
        return Agent(
            model="gemini-2.0-flash-001",
            name="host_agent",
            instruction=self.root_instruction,
            before_model_callback=self.before_model_callback,
            description=(
                "This agent orchestrates the decomposition of the user request into tasks that can be performed by child agents."
            ),
            tools=[
                self.list_remote_agents,
                self.send_task,
            ]
        )

    def root_instruction(self, context: ReadonlyContext) -> str:
        current_agent = self.check_state(context)
        return f"""You are a expert delegator that can delegate the user request to the
        appropriate remote agents.

        Discovery:
        - You can use `list_remote_agents` to list the available remote agents you
        can use to delegate the task.

        Execution:
        - For actionable tasks, you can use `create_task` to assign tasks to remote agents to perform.
        Be sure to include the remote agent name when you response to the user.

        You can use `check_pending_task_states` to check the states of the pending
        tasks.

        Please rely on tools to address the request, don't make up the response. If you are not sure, please ask the user for more details.
        Focus on the most recent parts of the conversation primarily.

        If there is an active agent, send the request to that agent with the update task tool.

        Agents:
        {self.agents}

        Current agent: {current_agent['active_agent']}
        """

    def check_state(self, context: ReadonlyContext):
        state = context.state
        if ('session_id' in state and
                'session_active' in state and
                state['session_active'] and 'agent' in state):
            return {"active_agent": f"{state['agent']}"}
        else:
            return {"active_agent": "None"}

    def before_model_callback(self, callback_context: CallbackContext, llm_request):
        state = callback_context.state
        if 'session_active' not in state or not state['session_active']:
            if 'session_id' not in state:
                state['session_id'] = str(uuid.uuid4())
            state['session_active'] = True

    def list_remote_agents(self):
        if not self.remote_agent_connections:
            return []

        remote_agent_info = []
        for card in self.cards.values():
            remote_agent_info.append({
                "name": card.name,
                "description": card.description,
            })
        return remote_agent_info

    async def send_task(self,
                        agent_name: str,
                        message: str,
                        tool_context: ToolContext):
        if agent_name not in self.remote_agent_connections:
            raise ValueError(f"Agent {agent_name} not found")
        state = tool_context.state
        state['agent'] = agent_name
        card = self.cards[agent_name]
        client = self.remote_agent_connections[agent_name]
        if not client:
            raise ValueError(f"Agent {agent_name} not found")
        if 'task_id' in state:
            task_id = state['task_id']
        else:
            task_id = state['session_id']

        session_id = state['session_id']
        task: Task
        message_id = ""
        meta_data = {}
        if 'input_message_metadata' in state:
            meta_data.update(**state['input_message_metadata'])
            if 'message_id' in state['input_message_metadata']:
                message_id = state['input_message_metadata']['message_id']
        if not message_id:
            message_id = str(uuid.uuid4())
        meta_data.update(**{"conversation_id": session_id, "message_id": message_id})
        request: TaskSendParams = TaskSendParams(
            id=task_id,
            sessionId=session_id,
            message=Message(
                role="user",
                parts=[TextPart(text=message)],
                meta_data=meta_data
            ),
            acceptedOutputModels=['text', 'text/plain', 'image/png'],
            meta_data={"conversation_id": session_id}
        )
        task = await client.send_task(request, self.task_callback)
        state['session_active'] = task.status.state not in [
            TaskState.COMPLETED,
            TaskState.CANCELLED,
            TaskState.FAILED,
            TaskState.UNKNOWN
        ]

        if task.status.state == TaskState.INPUT_REQUIRED:
            tool_context.actions.skip_summarization = True
            tool_context.actions.escalate = True

        elif task.status.state == TaskState.CANCELLED:
            raise ValueError(f"Agent {agent_name} task {task.id} is cancelled")

        elif task.status.state == TaskState.FAILED:
            raise ValueError(f"Agent {agent_name} task {task.id} is failed")

        response = []
        if task.status.message:
            response.extend(convert_parts(task.status.message.parts, tool_context))
        if task.artifacts:
            for artifact in task.artifacts:
                response.extend(convert_parts(artifact.parts, tool_context))
        return response
