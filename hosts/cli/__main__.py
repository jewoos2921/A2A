from common.client import A2ACardResolver, A2AClient
from common.types import Task, TaskState
from common.utils.push_notification_auth import PushNotificationReceiverAuth
import asyncclick as click
import asyncio
from uuid import uuid4
import urllib


@click.command()
@click.option('--agent', default="http://localhost:10000")
@click.option('--session', default=0)
@click.option('--history', default=False)
@click.option('--use_push_notification', default=False)
@click.option('--push_notification_receiver', default="http://localhost:5000")
async def cli(agent, session, history,
              use_push_notification: bool,
              push_notification_receiver: str):
    card_resolver = A2ACardResolver(agent)
    card = card_resolver.get_agent_card()

    print("======== Agent Card ==========")
    print(card.model_dump_json(exclude_none=True))

    notif_receiver_parsed = urllib.parse.urlparse(push_notification_receiver)
    notif_receiver_host = notif_receiver_parsed.hostname
    notif_receiver_port = notif_receiver_parsed.port

    if use_push_notification:
        from hosts.cli.push_notification_listener import PushNotificationListener
        push_notification_auth = PushNotificationReceiverAuth()
        await push_notification_auth.load_jwks(f"{agent}/.well-known/jwks.json")

        push_notification_listener = PushNotificationListener(
            host=notif_receiver_host,
            port=notif_receiver_port,
            notification_receiver_auth=push_notification_auth)
        push_notification_listener.start()

    client = A2AClient(agent_card=card)
    if session == 0:
        session_id = uuid4().hex
    else:
        session_id = session

    continue_loop = True
    streaming = card.capabilities.streaming

    while continue_loop:
        task_id = uuid4().hex
        print("============ starting a new task ================")

        continue_loop = await  complete_task(client, streaming, use_push_notification, notif_receiver_host,
                                             notif_receiver_port,
                                             task_id, session_id)
        if history and continue_loop:
            print("============ starting a new task ================")
            task_response = await  client.get_task({"id": task_id,
                                                    "historyLength": 10})
            print(task_response.model_dump_json(include={"result": {"history": True}}))


async def complete_task(client, streaming, use_push_notification, notif_receiver_host, notif_receiver_port, task_id,
                        session_id):
    prompt = click.prompt(
        "\What do you want to send to the agent? (:q or quit to exit)"
    )
    if prompt == ":q" or prompt == "quit":
        return False

    payload = {
        "id": task_id, "sessionId": session_id,
        "acceptedOutputModes": ['text'],
        "message": {
            "role": "user",
            "parts": [
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }
    }

    if use_push_notification:
        payload["pushNotification"] = {
            "url": f'http://{notif_receiver_host}:{notif_receiver_port}/notify',
            "authentication": {
                "schemes": ["bearer"]
            }
        }
