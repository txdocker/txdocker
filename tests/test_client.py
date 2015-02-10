# coding: utf-8

import json
import mock
import treq

from twisted.python.failure import Failure
from twisted.internet.defer import succeed
from twisted.trial.unittest import TestCase
from twisted.web.client import ResponseDone

from txdocker.client import Client


class _Response(object):
    """
    A fake response (not a verified fake - does not contain every attribute
    and method of a true Response - missing headers, for instance) that can
    also fake delivering a body

    The status code accepted is an int, and the body either None or a
    json blob (which will be converted to a string).
    """

    def __init__(self, status_code=204, body=None):
        self.code = status_code
        self._body = json.dumps(body)

        self.length = len(self._body)

    def deliverBody(self, iproducer):
        # replicate the same brokeness in Twisted:  if the status code is 204,
        # dataReceived and connectionLost are never called
        iproducer.dataReceived(self._body)
        iproducer.connectionLost(Failure(ResponseDone()))


class ClientCommands(TestCase):
    """
    Tests commands (methods on Client)
    """

    def setUp(self):
        """
        Wraps treq so that actual calls are mostly made, but that certain
        results can be stubbed out
        """

        self.treq = mock.patch('txdocker.client.treq', wraps=treq).start()
        self.addCleanup(mock.patch.stopall)

    def test_wait(self):
        """
        The correct parameters are passed to treq.post, and the JSON result is
        returned as a dict
        """

        self.treq.post.return_value = succeed(
            _Response(200, {'StatusCode': 0}))

        d = Client().wait(host=mock.Mock(url='http://localhost'),
                          container=mock.Mock(id='__id__'))

        self.treq.post.assert_called_once_with(
            url="http://localhost/v1.6/containers/__id__/wait",
            params={},
            pool=mock.ANY)

        self.assertEqual({'StatusCode': 0}, self.successResultOf(d))
