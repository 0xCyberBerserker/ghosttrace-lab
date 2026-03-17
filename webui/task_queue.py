import json
import os
import time
from typing import Callable

import pika


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "").strip()
RABBITMQ_TRIAGE_QUEUE = os.getenv("RABBITMQ_TRIAGE_QUEUE", "ghosttrace.triage")


def rabbitmq_enabled() -> bool:
    return bool(RABBITMQ_URL)


def publish_json(queue_name: str, payload: dict) -> bool:
    if not rabbitmq_enabled():
        return False

    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        return True
    finally:
        connection.close()


def consume_json(queue_name: str, handler: Callable[[dict], None], poll_interval: float = 5.0) -> None:
    if not rabbitmq_enabled():
        raise RuntimeError("RabbitMQ is not configured.")

    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_qos(prefetch_count=1)

            def _callback(ch, method, properties, body):
                payload = json.loads(body.decode("utf-8"))
                try:
                    handler(payload)
                except Exception:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    return
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=queue_name, on_message_callback=_callback)
            channel.start_consuming()
        except KeyboardInterrupt:
            raise
        except Exception:
            time.sleep(poll_interval)
        finally:
            try:
                connection.close()
            except Exception:
                pass
