import json
import logging
from pathlib import Path
from google.cloud import pubsub_v1

import config

logger = logging.getLogger(__name__)

_publisher: pubsub_v1.PublisherClient | None = None


def _make_publisher() -> pubsub_v1.PublisherClient:
    key = config.PUBSUB_KEY_PATH
    if key and Path(key).exists():
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            key,
            scopes=["https://www.googleapis.com/auth/pubsub"],
        )
        return pubsub_v1.PublisherClient(credentials=creds)
    return pubsub_v1.PublisherClient()


def get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = _make_publisher()
    return _publisher


def reset_publisher() -> None:
    """Force recreation of the publisher client (call after config reload)."""
    global _publisher
    _publisher = None


def publish_to_pubsub(topic_path: str, payload: dict):
    """Publish a single JSON message to a Pub/Sub topic."""
    data = json.dumps(payload).encode("utf-8")
    try:
        future = get_publisher().publish(topic_path, data)
        future.result()
    except Exception as e:
        logger.error("Pub/Sub publish failed for %s: %s", topic_path, e)
        raise
