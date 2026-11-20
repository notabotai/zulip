from unittest.mock import patch

from django.db import connection

from zerver.lib.test_classes import ZulipTransactionTestCase
from zerver.models import ScheduledMessageNotificationEmail
from zerver.worker.missedmessage_emails import MissedMessageWorker


class MissedMessageWorkerConnectionTest(ZulipTransactionTestCase):
    def test_reconnects_after_broken_connection(self) -> None:
        mmw = MissedMessageWorker()

        def stop_instead_of_retrying(timeout: float) -> None:
            mmw.stopping = True

        connection.connection.close()

        with (
            patch.object(mmw.cv, "wait", side_effect=stop_instead_of_retrying),
            self.assertLogs(level="ERROR") as logs,
        ):
            mmw.work()

        self.assertIn("connection already closed", logs.output[0])
        self.assertEqual(ScheduledMessageNotificationEmail.objects.count(), 0)
