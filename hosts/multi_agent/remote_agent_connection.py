from typing import Callable
import uuid
from common.types import (
    AgentCard,
    Task,
    TaskSendParams,
    TaskArtifactUpdateEvent,
    TaskStatus,
    TaskState,
    TaskStatusUpdateEvent
)

from common.client import A2AClient

TaskCallbackArg = Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent
TaskUpdateCallback = Callable[[TaskCallbackArg, AgentCard], Task]


class RemoteAgentConnections:
    def __init__(self, agent_card: AgentCard):
        self.agent_client = A2AClient(agent_card)
        self.card = agent_card

        self.conversation_name = None
        self.conversation = None
        self.pending_tasks = set()

    def get_agent(self) -> AgentCard:
        return self.card

    async def send_task(self,
                        request: TaskSendParams,
                        task_callback: TaskUpdateCallback | None) -> Task | None:
        if self.card.capabilities.streaming:
            task = None
            if task_callback:
                task_callback(Task(
                    id=request.id,
                    sessionId=request.sessionId,
                    status=TaskStatus(
                        state=TaskState.SUBMITTED,
                        message=request.message,
                    ),
                    history=[request.message]
                ), self.card)

            async for response in self.agent_client.send_task_streaming(request.model_dump()):
                merge_metadata(response.result, request)
                if (hasattr(response.result, "status") and
                        hasattr(response.result.status, "message") and response.result.status.message):

                    merge_metadata(response.result.status.message, request.message)
                    m = response.result.status.message

                    if not m.meta_data:
                        m.meta_data = {}
                    if 'message_id' in m.meta_data:
                        m.meta_data['last_message_id'] = m.meta_data['message_id']
                    m.meta_data['message_id'] = str(uuid.uuid4())

                if task_callback:
                    task_callback(response.result, self.card)
                if hasattr(response.result, "final") and response.result.final:
                    break
            return task
        else:
            response = await self.agent_client.send_task(request.model_dump())
            merge_metadata(response.result, request)

            if (hasattr(response.result, "status") and
                    hasattr(response.result.status, "message") and
                    response.result.status.message):
                merge_metadata(response.result.status.message, request.message)
                m = response.result.status.message
                if not m.meta_data:
                    m.meta_data = {}
                if 'message_id' in m.meta_data:
                    m.meta_data['last_message_id'] = m.meta_data['message_id']
                m.meta_data['message_id'] = str(uuid.uuid4())

            if task_callback:
                task_callback(response.result)
            return response.result


def merge_metadata(target, source):
    if not hasattr(target, 'meta_data') or not hasattr(source, 'meta_data'):
        return
    if target.meta_data and source.meta_data:
        target.meta_data.update(source.meta_data)
    elif source.meta_data:
        target.meta_data = dict(**source.meta_data)
