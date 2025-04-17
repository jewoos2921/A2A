import httpx
from httpx_sse import connect_sse
from typing import Any, AsyncIterable
from common.types import *
import json


class A2AClient:
    def __init__(self, agent_card: AgentCard = None,
                 url: str = None):
        if agent_card:
            self.url = agent_card.url
        elif url:
            self.url = url
        else:
            raise ValueError("Either agent_card or url must be provided")

    async def send_task(self, payload: dict[str, Any]) -> SendTaskResponse:
        request = SendTaskRequest(**payload)
        return SendTaskResponse(**await self._send_request(request))

    async def send_task_streaming(self, payload: dict[str, Any]) -> AsyncIterable[SendTaskStreamingResponse]:
        request = SendTaskStreamingRequest(**payload)
        with httpx.Client(timeout=None) as client:
            with connect_sse(client, "POST", self.url, json=request.model_dump()) as event_source:
                try:
                    for sse in event_source.iter_sse():
                        yield SendTaskStreamingResponse(**json.loads(sse.data))
                except json.JSONDecodeError as e:
                    raise A2AClientJSONError(str(e)) from e
                except httpx.HTTPError as e:
                    raise A2AClientHTTPError(400, str(e)) from e

    async def _send_request(self, request: JSONRPCRequest) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, json=request.model_dump(), timeout=30)
                response.raise_for_status()
                return response.json()
            except json.JSONDecodeError as e:
                raise A2AClientJSONError(str(e)) from e
            except httpx.HTTPError as e:
                raise A2AClientHTTPError(response.status_code, str(e)) from e

    async def get_task(self, payload: dict[str, Any]) -> GetTaskResponse:
        request = GetTaskRequest(**payload)
        return GetTaskResponse(**await self._send_request(request))

    async def cancel_task(self, payload: dict[str, Any]) -> CancelTaskResponse:
        request = CancelTaskRequest(**payload)
        return CancelTaskResponse(**await self._send_request(request))

    async def set_task_callback(self, payload: dict[str, Any]) -> SetTaskPushNotificationResponse:
        request = SetTaskPushNotificationRequest(**payload)
        return SetTaskPushNotificationResponse(**await self._send_request(request))

    async def get_task_callback(self, payload: dict[str, Any]) -> GetTaskPushNotificationResponse:
        request = GetTaskPushNotificationRequest(**payload)
        return GetTaskPushNotificationResponse(**await self._send_request(request))
