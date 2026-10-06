from typing import Any
from unittest import mock

import orjson
from django.conf import settings
from django.core import mail
from django.db import IntegrityError
from django.utils.timezone import now as timezone_now

from zerver.actions.message_send import create_mirror_user_if_needed
from zerver.actions.realm_settings import do_set_realm_user_default_setting
from zerver.actions.users import do_change_can_forge_sender
from zerver.lib.create_user import create_user_profile
from zerver.lib.test_classes import ZulipTestCase
from zerver.lib.test_helpers import reset_email_visibility_to_everyone_in_zulip_realm
from zerver.models import RealmUserDefault, ScheduledEmail, UserProfile
from zerver.models.clients import get_client
from zerver.models.realms import get_realm
from zerver.models.users import get_system_bot, get_user
from zerver.views.message_send import InvalidMirrorInputError, create_mirrored_message_users


class MirroredMessageUsersTest(ZulipTestCase):
    def test_invalid_client(self) -> None:
        user = self.example_user("hamlet")
        sender = user

        recipients: list[str] = []

        recipient_type_name = "private"
        client = get_client("banned_mirror")

        with self.assertRaises(InvalidMirrorInputError):
            create_mirrored_message_users(
                client, user, recipients, sender.email, recipient_type_name
            )

    def test_invalid_email(self) -> None:
        invalid_email = "alice AT example.com"
        recipients = [invalid_email]

        # We use an MIT user here to maximize code coverage
        user = self.mit_user("starnine")
        sender = user

        recipient_type_name = "private"

        for client_name in ["irc_mirror", "jabber_mirror"]:
            client = get_client(client_name)

            with self.assertRaises(InvalidMirrorInputError):
                create_mirrored_message_users(
                    client, user, recipients, sender.email, recipient_type_name
                )

    def test_mirror_new_recipient(self) -> None:
        """Test mirror dummy user creation for direct message recipients"""
        user = self.mit_user("starnine")
        sender = self.mit_user("sipbtest")
        new_user_email = "bob_the_new_user@mit.edu"
        new_user_realm = get_realm("zephyr")

        recipients = [user.email, new_user_email]

        recipient_type_name = "private"
        client = get_client("irc_mirror")

        mirror_sender = create_mirrored_message_users(
            client, user, recipients, sender.email, recipient_type_name
        )

        self.assertEqual(mirror_sender, sender)

        realm_users = UserProfile.objects.filter(realm=sender.realm)
        realm_emails = {user.email for user in realm_users}
        self.assertIn(user.email, realm_emails)
        self.assertIn(new_user_email, realm_emails)

        bob = get_user(new_user_email, new_user_realm)
        self.assertTrue(bob.is_mirror_dummy)

    def test_mirror_new_sender(self) -> None:
        """Test mirror dummy user creation for sender when sending to stream"""
        user = self.mit_user("starnine")
        sender_email = "new_sender@mit.edu"

        recipients = ["stream_name"]

        recipient_type_name = "stream"
        client = get_client("irc_mirror")

        mirror_sender = create_mirrored_message_users(
            client, user, recipients, sender_email, recipient_type_name
        )

        assert mirror_sender is not None
        self.assertEqual(mirror_sender.email, sender_email)
        self.assertTrue(mirror_sender.is_mirror_dummy)

    def test_irc_mirror(self) -> None:
        reset_email_visibility_to_everyone_in_zulip_realm()

        user = self.example_user("hamlet")
        sender = user

        recipients = [
            self.nonreg_email("alice"),
            "bob@irc.zulip.com",
            self.nonreg_email("cordelia"),
        ]

        recipient_type_name = "private"
        client = get_client("irc_mirror")

        mirror_sender = create_mirrored_message_users(
            client, user, recipients, sender.email, recipient_type_name
        )

        self.assertEqual(mirror_sender, sender)

        realm_users = UserProfile.objects.filter(realm=sender.realm)
        realm_emails = {user.email for user in realm_users}
        self.assertIn(self.nonreg_email("alice"), realm_emails)
        self.assertIn("bob@irc.zulip.com", realm_emails)

        bob = get_user("bob@irc.zulip.com", sender.realm)
        self.assertTrue(bob.is_mirror_dummy)

    def test_jabber_mirror(self) -> None:
        reset_email_visibility_to_everyone_in_zulip_realm()

        user = self.example_user("hamlet")
        sender = user

        recipients = [
            self.nonreg_email("alice"),
            self.nonreg_email("bob"),
            self.nonreg_email("cordelia"),
        ]

        recipient_type_name = "private"
        client = get_client("jabber_mirror")

        mirror_sender = create_mirrored_message_users(
            client, user, recipients, sender.email, recipient_type_name
        )

        self.assertEqual(mirror_sender, sender)

        realm_users = UserProfile.objects.filter(realm=sender.realm)
        realm_emails = {user.email for user in realm_users}
        self.assertIn(self.nonreg_email("alice"), realm_emails)
        self.assertIn(self.nonreg_email("bob"), realm_emails)

        bob = get_user(self.nonreg_email("bob"), sender.realm)
        self.assertTrue(bob.is_mirror_dummy)

    def test_jabber_mirror_new_sender_with_masked_email_visibility(self) -> None:
        """A forged jabber_mirror send from a never-seen address must succeed
        even when the realm masks new users' .email, and every later send
        from that address must reuse the one mirror dummy it created."""
        realm = get_realm("zulip")
        do_set_realm_user_default_setting(
            RealmUserDefault.objects.get(realm=realm),
            "email_address_visibility",
            RealmUserDefault.EMAIL_ADDRESS_VISIBILITY_MODERATORS,
            acting_user=None,
        )
        bot = self.create_test_bot("jabber", self.example_user("iago"))
        do_change_can_forge_sender(bot, True)

        sender_email = "918299339223@zulip.com"
        self.assertFalse(
            UserProfile.objects.filter(realm=realm, delivery_email__iexact=sender_email).exists()
        )
        outbox_before = len(mail.outbox)
        scheduled_emails_before = ScheduledEmail.objects.count()

        # Twice: the bug made the first send *and every later one* fail.
        for content in ["first message", "second message"]:
            result = self.api_post(
                bot,
                "/api/v1/messages",
                {
                    "type": "channel",
                    "to": orjson.dumps("Verona").decode(),
                    "topic": "from whatsapp",
                    "content": content,
                    "client": "jabber_mirror",
                    "forged": "true",
                    "sender": sender_email,
                },
            )
            self.assert_json_success(result)

            dummies = UserProfile.objects.filter(realm=realm, delivery_email__iexact=sender_email)
            self.assert_length(dummies, 1)
            dummy = dummies[0]
            # The masked .email is what the old get_user() lookup missed.
            self.assertNotEqual(dummy.email, dummy.delivery_email)
            self.assertTrue(dummy.is_mirror_dummy)
            self.assertFalse(dummy.is_active)
            self.assertEqual(dummy.full_name, "918299339223")

            message = self.get_last_message()
            self.assertEqual(message.sender_id, dummy.id)
            self.assertEqual(message.content, content)

        # Creating the placeholder account must not email anyone.
        self.assert_length(mail.outbox, outbox_before)
        self.assertEqual(ScheduledEmail.objects.count(), scheduled_emails_before)

    def test_jabber_mirror_cross_realm_bot_sender(self) -> None:
        """A cross-realm bot's address still resolves to the system bot, not
        to an account with that address in the forging user's realm."""
        user = self.example_user("hamlet")
        mirror_sender = create_mirrored_message_users(
            get_client("jabber_mirror"), user, [], settings.NOTIFICATION_BOT, "stream"
        )
        self.assertEqual(mirror_sender, get_system_bot(settings.NOTIFICATION_BOT, user.realm_id))

    def test_create_mirror_user_despite_race(self) -> None:
        realm = get_realm("zulip")

        email = "fred@example.com"

        email_to_full_name = lambda email: "fred"

        def create_user(**kwargs: Any) -> UserProfile:
            self.assertEqual(kwargs["full_name"], "fred")
            self.assertEqual(kwargs["email"], email)
            self.assertEqual(kwargs["active"], False)
            self.assertEqual(kwargs["is_mirror_dummy"], True)
            # We create an actual user here to simulate a race.
            # We use the minimal, un-mocked function.
            kwargs["bot_type"] = None
            kwargs["bot_owner"] = None
            kwargs["tos_version"] = None
            kwargs["timezone"] = timezone_now()
            kwargs["default_language"] = "en"
            kwargs["email_address_visibility"] = UserProfile.EMAIL_ADDRESS_VISIBILITY_EVERYONE
            create_user_profile(**kwargs).save()
            raise IntegrityError

        with mock.patch("zerver.actions.message_send.create_user", side_effect=create_user) as m:
            mirror_fred_user = create_mirror_user_if_needed(
                realm,
                email,
                email_to_full_name,
            )

        self.assertEqual(mirror_fred_user.delivery_email, email)
        m.assert_called()
