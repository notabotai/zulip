import os
from unittest import mock

import orjson
import responses
from django.test import override_settings
from requests.exceptions import ConnectionError

from zerver.lib.push_notifications import handle_push_notification
from zerver.lib.test_classes import ZulipTestCase
from zerver.models import UserMessage
from zerver.models.scheduled_jobs import NotificationTriggers


@override_settings(
    NB_WEBPUSH_URL="http://127.0.0.1:9180/internal/notify",
    ZULIP_SERVICE_PUSH_NOTIFICATIONS=False,
    APNS_TOKEN_KEY_FILE=None,
    APNS_CERT_FILE=None,
)
class NbWebpushTest(ZulipTestCase):
    @mock.patch.dict(os.environ, {"HTTP_proxy": "http://localhost:4750"})
    @responses.activate
    def test_dm(self) -> None:
        sender = self.example_user("othello")
        recipient = self.example_user("hamlet")
        responses.post("http://127.0.0.1:9180/internal/notify", status=200)
        message_id = self.send_personal_message(sender, recipient, "**Hello** " + "x" * 220)
        # Fixture users have no push device rows and no event queue, so the
        # send alone must reach the hand-off.
        self.assert_length(responses.calls, 1)

        # Reprocessing the queue event must not send a second notification.
        handle_push_notification(
            recipient.id, {"message_id": message_id, "trigger": NotificationTriggers.DIRECT_MESSAGE}
        )

        self.assert_length(responses.calls, 1)
        body = responses.calls[0].request.body
        assert isinstance(body, bytes)
        self.assertEqual(
            orjson.loads(body),
            {
                "user_id": recipient.id,
                "message_id": message_id,
                "sender_full_name": sender.full_name,
                "is_dm": True,
                "channel_name": None,
                "topic": None,
                "trigger": NotificationTriggers.DIRECT_MESSAGE,
                "snippet": "Hello " + "x" * 194,
            },
        )
        # The notifier is local, so the hand-off must skip the outgoing proxy.
        self.assertEqual(responses.calls[0].request.req_kwargs["proxies"], {})  # type: ignore[attr-defined]

    @responses.activate
    def test_channel_mention(self) -> None:
        sender = self.example_user("othello")
        recipient = self.example_user("hamlet")
        self.subscribe(sender, "Denmark")
        responses.post("http://127.0.0.1:9180/internal/notify", status=200)
        message_id = self.send_stream_message(
            sender, "Denmark", f"@**{recipient.full_name}** hello", topic_name="Greetings"
        )

        self.assert_length(responses.calls, 1)
        body = responses.calls[0].request.body
        assert isinstance(body, bytes)
        self.assertEqual(
            orjson.loads(body),
            {
                "user_id": recipient.id,
                "message_id": message_id,
                "sender_full_name": sender.full_name,
                "is_dm": False,
                "channel_name": "Denmark",
                "topic": "Greetings",
                "trigger": NotificationTriggers.MENTION,
                "snippet": f"@{recipient.full_name} hello",
            },
        )

    @override_settings(NB_WEBPUSH_URL=None)
    @responses.activate
    def test_unset(self) -> None:
        recipient = self.example_user("hamlet")
        message_id = self.send_personal_message(self.example_user("othello"), recipient)
        handle_push_notification(
            recipient.id, {"message_id": message_id, "trigger": NotificationTriggers.DIRECT_MESSAGE}
        )
        self.assert_length(responses.calls, 0)
        self.assertFalse(
            UserMessage.objects.get(
                user_profile=recipient, message_id=message_id
            ).flags.active_mobile_push_notification
        )

    @responses.activate
    def test_inaccessible_sender(self) -> None:
        responses.post("http://127.0.0.1:9180/internal/notify", status=200)
        self.set_up_db_for_testing_user_access()
        sender = self.example_user("hamlet")
        recipient = self.example_user("polonius")
        self.unsubscribe(sender, "test_stream1")
        self.send_stream_message(
            sender,
            "test_stream1",
            f"@**{recipient.full_name}** hello",
            allow_unsubscribed_sender=True,
        )

        # The setup's direct messages hand off first.
        body = responses.calls[-1].request.body
        assert isinstance(body, bytes)
        self.assertEqual(orjson.loads(body)["sender_full_name"], "Unknown user")

    @responses.activate
    def test_read_or_inaccessible_message(self) -> None:
        recipient = self.example_user("hamlet")
        responses.post("http://127.0.0.1:9180/internal/notify", status=200)
        message_id = self.send_personal_message(self.example_user("othello"), recipient)
        # Marking it read also clears the active push notification flag.
        UserMessage.objects.filter(user_profile=recipient, message_id=message_id).update(
            flags=UserMessage.flags.read
        )
        missed_message = {"message_id": message_id, "trigger": NotificationTriggers.DIRECT_MESSAGE}
        handle_push_notification(recipient.id, missed_message)
        handle_push_notification(self.example_user("cordelia").id, missed_message)
        # Only the send's own hand-off.
        self.assert_length(responses.calls, 1)

    @responses.activate
    def test_notifier_errors(self) -> None:
        recipient = self.example_user("hamlet")
        for error in (ConnectionError("Notifier unavailable"), b""):
            with self.subTest(error=error):
                responses.post("http://127.0.0.1:9180/internal/notify", body=error, status=500)
                with self.assertLogs("zerver.lib.nb_webpush", level="WARNING") as logs:
                    self.send_personal_message(self.example_user("othello"), recipient)
                self.assertIn("Web push hand-off failed", logs.output[0])
