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

        self.client = Client('unix:///var/run/docker.sock')
        self.mock = mock.Mock(self.client.client, wrap=self.client.client)
        self.client.client = self.mock
        self.addCleanup(mock.patch.stopall)


    def test_info(self):
        self.mock.get.return_value = succeed(
            _Response(200, {'StatusCode': 0}))

        d = self.client.info()

        self.mock.get.assert_called_once_with(
            url="unix:///v1.8/info",
            params={},
            pool=mock.ANY)

        self.assertEqual({'StatusCode': 0}, self.successResultOf(d))

    def test_version(self):
        self.mock.get.return_value = succeed(
            _Response(200, {'StatusCode': 0}))

        d = self.client.version()

        self.mock.get.assert_called_once_with(
            url="unix:///v1.8/version",
            params={},
            pool=mock.ANY)

        self.assertEqual({'StatusCode': 0}, self.successResultOf(d))

    def test_wait(self):
        """
        The correct parameters are passed to treq.post, and the JSON result is
        returned as a dict
        """

        self.mock.post.return_value = succeed(
            _Response(200, {'StatusCode': 0}))

        d = self.client.wait(container=mock.Mock(id='__id__'))

        self.mock.post.assert_called_once_with(
            url="unix:///v1.8/containers/__id__/wait",
            params={},
            pool=mock.ANY)

        self.assertEqual({'StatusCode': 0}, self.successResultOf(d))

