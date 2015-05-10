# coding: utf-8
"""
Twisted based client with parallel execution in mind and fixes
quirks of the official docker-py client.
"""

import re
import json
import logging
import logging.handlers
from copy import copy

from zope.interface import implementer

from twisted.web.iweb import IAgentEndpointFactory
from twisted.internet import reactor
from twisted.internet.endpoints import UNIXClientEndpoint
from twisted.internet.defer import Deferred, succeed
from twisted.internet.protocol import Protocol
from twisted.web.client import Agent, HTTPConnectionPool, ResponseDone

import treq

from txdocker.errors import assert_code


@implementer(IAgentEndpointFactory)
class DockerEndpointFactory(object):
    """
    Connect to Docker's Unix socket.
    """
    def __init__(self, reactor, socket=b'/var/run/docker.sock'):
        self.reactor = reactor
        self.socket = socket

    def endpointForURI(self, uri):
        return UNIXClientEndpoint(self.reactor, self.socket)


class Client(object):
    """A generic twisted-based docker client that supports all sorts of
    docker magic like streaming replies and http session hijacking on
    container attach.
    """

    pool = None
    log = None

    def __init__(self, host, api_version="1.8", timeout=None, log=None, pool=None):
        self.api_version = api_version
        self.timeout = timeout
        self.pool = pool or HTTPConnectionPool(reactor, persistent=False)
        self.log = log or logging.getLogger(__name__)

        if host.startswith('unix:///'):
            self.host, socket = host[:7], host[7:]
            factory = DockerEndpointFactory(reactor, socket)
            self.agent = Agent.usingEndpointFactory(reactor, factory)
        else:
            self.host = host
            self.agent = Agent(reactor, pool=self.pool)
        self.client = treq.client.HTTPClient(self.agent)

    def request(self, method, path, **kwargs):
        kwargs = copy(kwargs)
        kwargs['params'] = _remove_empty(kwargs.get('params'))
        if not kwargs['params']:
            del kwargs['params']
        kwargs['pool'] = self.pool

        post_json = kwargs.pop('post_json', False)
        if post_json:
            headers = kwargs.setdefault('headers', {})
            headers['Content-Type'] = ['application/json']
            kwargs['data'] = json.dumps(kwargs['data'])

        kwargs['url'] = self._make_url(path)
        expect_json = kwargs.pop('expect_json', True)

        result = Deferred()
        d = method(**kwargs)

        def content(response):
            response_content = []
            cd = treq.collect(response, response_content.append)
            cd.addCallback(lambda _: ''.join(response_content))
            cd.addCallback(done, response)
            return cd

        def done(response_content, response):
            assert_code(response.code, response_content)
            if expect_json:
                return json.loads(response_content)
            return response_content

        d.addCallback(content)
        d.addCallback(result.callback)
        d.addErrback(result.errback)

        return result

    def get(self, path, **kwargs):
        return self.request(self.client.get, path, **kwargs)

    def post(self, path, **kwargs):
        return self.request(self.client.post, path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request(self.client.delete, path, **kwargs)

    def _make_url(self, method):
        return "{}/v{}/{}".format(self.host, self.api_version, method)

    def info(self):
        return self.get('info')

    def version(self):
        return self.get('version')

    def wait(self, container_id):
        """Waits for the container to stop and gets the exit code"""

        def log_results(results):
            self.log.debug("{0} has stopped with exit code {1}".format(
                container_id, results['StatusCode']))
            return results

        d = self.post(
            "containers/{}/wait".format(container_id),
            expect_json=True)

        d.addCallback(log_results)
        return d

    def images(self, all=False):
        params = {
            'all': all,
        }
        return self.get('images/json', params=params)

    def containers(self, all=False, since=None, before=None, limit=-1, size=None):
        params = {
            'all': all,
            'limit': limit,
            'since': since,
            'before': before,
            'size': size,
        }
        return self.get('containers/json', params=params)

    def create_container(self, config, name=None):
        params = {}
        if name:
            params['name'] = name
        return self.post(
            "containers/create",
            params=params,
            data=config,
            post_json=True)

    def inspect(self, container_id):
        return self.get(
            "containers/{}/json".format(container_id),
            expect_json=True)

    def start(self, host, container, binds=None, port_binds=None, links=[]):
        self.log.debug("Starting {} {} {}".format(container,
                                                  binds, port_binds))
        data = {}
        if binds:
            data['Binds'] = binds
        if port_binds:
            data['PortBindings'] = port_binds
        if links:
            data['Links'] = links

        return self.post(
            host, "containers/{}/start".format(container.id),
            data=data,
            post_json=True,
            expect_json=False)

    def stop(self, host, container, wait_seconds=5):
        self.log.debug("Stopping {}".format(container))
        return self.post(host, "containers/{}/stop".format(container.id),
                         params={'t': wait_seconds},
                         expect_json=False)

    def attach(self, host, container, **kwargs):
        def c(v):
            return 1 if kwargs.get(v) else 0
        params = {
            'logs': c('logs'),
            'stream': c('stream'),
            'stdin': 0,
            'stdout': c('stdout'),
            'stderr': c('stderr')
        }

        result = Deferred()

        def on_content(line):
            if line:
                self.log.debug("{}: {}".format(host, line.strip()))

        url = self._make_url(
            host.url, 'containers/{}/attach'.format(container.id))
        d = treq.post(
            url=url,
            params=params,
            pool=self.pool)

        d.addCallback(_Reader.listen, kwargs.get('stop_line'))

        def on_error(failure):
            pass
        d.addErrback(on_error)
        return result

    def build(self, host, dockerfile, tag=None, quiet=False,
              nocache=False, rm=False):
        """
        Run build of a container from buildfile
        that can be passed as local/remote path or file object(fobj)
        """

        params = {
            'q': quiet,
            'nocache': nocache,
            'rm': rm
        }

        if dockerfile.is_remote:
            params['remote'] = dockerfile.url
        if tag:
            params['t'] = tag

        headers = {}
        if not dockerfile.is_remote:
            headers = {'Content-Type': 'application/tar'}

        container = []
        result = Deferred()

        def on_content(line):
            if line:
                self.log.debug("{}: {}".format(host, line.strip()))
                match = re.search(r'Successfully built ([0-9a-f]+)', line)
                if match:
                    container.append(match.group(1))

        d = treq.post(
            url=self._make_url(host.url, 'build'),
            data=dockerfile.archive,
            params=params,
            headers=headers,
            pool=self.pool)

        def on_done(*args, **kwargs):
            if not container:
                result.errback(RuntimeError("Build failed"))
            else:
                result.callback(container[0])

        d.addCallback(treq.collect, on_content)
        d.addBoth(on_done)
        return result


def _remove_empty(params):
    params = params or {}
    clean_params = copy(params)
    for key, val in params.iteritems():
        if val is None:
            del clean_params[key]
    return clean_params


class _Reader(Protocol):
    def __init__(self, finished, stop_line):
        self.finished = finished
        if stop_line:
            self.stop_line = re.compile(stop_line, re.I)
        else:
            self.stop_line = None

    def dataReceived(self, data):
        if self.stop_line and self.stop_line.search(data):
            self.transport._producer.looseConnection()

    def connectionLost(self, reason):
        if reason.check(ResponseDone):
            self.finished.callback(None)
            return
        self.finished.errback(reason)

    @classmethod
    def listen(cls, response, data):
        if response.length == 0:
            return succeed(None)
        d = Deferred()
        response.deliverBody(cls(d, data))
        return d
