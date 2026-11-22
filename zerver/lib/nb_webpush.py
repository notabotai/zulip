import logging

import requests
from django.conf import settings

from zerver.lib.users import check_can_access_user
from zerver.models import Message, UserProfile

logger = logging.getLogger(__name__)


def send_nb_webpush(user_profile: UserProfile, message: Message, trigger: str) -> None:
    # Import here because push_notifications calls this helper.
    from zerver.lib.push_notifications import (
        get_message_stream_name_from_database,
        get_mobile_push_content,
    )

    if not settings.NB_WEBPUSH_URL:
        return

    try:
        assert message.rendered_content is not None
        sender_name = message.sender.full_name
        if message.is_channel_message and not check_can_access_user(
            message.sender, user_profile, message.realm
        ):
            sender_name = str(UserProfile.INACCESSIBLE_USER_NAME)
        # The notifier is local, and Zulip's outgoing proxy (the HTTP_proxy
        # environment variable) refuses private addresses, so don't use it.
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                settings.NB_WEBPUSH_URL,
                json={
                    "user_id": user_profile.id,
                    "message_id": message.id,
                    "sender_full_name": sender_name,
                    "is_dm": not message.is_channel_message,
                    "channel_name": (
                        get_message_stream_name_from_database(message)
                        if message.is_channel_message
                        else None
                    ),
                    "topic": message.topic_name() if message.is_channel_message else None,
                    "trigger": trigger,
                    "snippet": get_mobile_push_content(message.rendered_content)[:200],
                },
                timeout=2,
            )
            response.raise_for_status()
    except Exception:
        logger.warning("Web push hand-off failed for message %s", message.id, exc_info=True)
