# coding: utf-8

import json
import mock
import treq

from twisted.python.failure import Failure
from twisted.internet.defer import succeed
from twisted.trial.unittest import TestCase
from twisted.web.client import ResponseDone

from txdocker.client import Client
from txdocker.config import ContainerConfig

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


    def set_get_200(self):
        self.mock.get.return_value = succeed(
            _Response(200, {'StatusCode': 0}))

    def set_post_200(self):
        self.mock.post.return_value = succeed(
            _Response(200, {'StatusCode': 0}))

    def get_url(self, endpoint, version='1.8'):
        return "unix:///v{}/{}".format(version, endpoint)

    def assert_get_once(self, d, endpoint, **kwargs):
        kwargs['url'] = self.get_url(endpoint)
        kwargs['pool'] = mock.ANY
        self.mock.get.assert_called_once_with(**kwargs)
        self.assertEqual({'StatusCode': 0}, self.successResultOf(d))

    def assert_post_once(self, d, endpoint, **kwargs):
        kwargs['url'] = self.get_url(endpoint)
        kwargs['pool'] = mock.ANY
        self.mock.post.assert_called_once_with(**kwargs)
        self.assertEqual({'StatusCode': 0}, self.successResultOf(d))

    def test_info(self):
        self.set_get_200()
        d = self.client.info()
        self.assert_get_once(d, 'info')

    def test_version(self):
        self.set_get_200()
        d = self.client.version()
        self.assert_get_once(d, 'version')

    def test_wait(self):
        """
        The correct parameters are passed to treq.post, and the JSON result is
        returned as a dict
        """
        self.set_post_200()
        d = self.client.wait('__id__')
        self.assert_post_once(d, "containers/__id__/wait")

    def test_images(self):
        self.set_get_200()
        d = self.client.images()
        self.assert_get_once(d, "images/json", params={'all':False})

    def test_containers(self):
        self.set_get_200()
        d = self.client.containers()
        self.assert_get_once(d, "containers/json", params={
            'all':False,
            'limit': -1,})

    def test_create_container(self):
        self.set_post_200()
        config = ContainerConfig('foo/bar:latest')
        d = self.client.create_container(config)
        self.assert_post_once(
            d, "containers/create",
            headers={'Content-Type': ['application/json']},
            data=json.dumps(config))

    def test_inspect(self):
        self.set_get_200()
        d = self.client.inspect("__id__")
        self.assert_get_once(d, "containers/__id__/json")


