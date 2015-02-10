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

from twisted.internet import reactor
from twisted.web.client import HTTPConnectionPool
from twisted.internet.defer import Deferred, succeed
from twisted.internet.protocol import Protocol
from twisted.web.client import ResponseDone
import treq

from .errors import assert_code


class Client(object):
    """A generic twisted-based docker client that supports all sorts of
    docker magic like streaming replies and http session hijacking on
    container attach.
    """

    pool = None
    log = None

    def __init__(self, version="1.6", timeout=None, log=None, pool=None):
        self.pool = pool or HTTPConnectionPool(reactor, persistent=False)
        self.version = version
        self.timeout = timeout
        self.log = log or logging.getLogger(__name__)

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

    def images(self, host, name=None, quiet=False,
               all=False, viz=False, pretty=False):
        path = "images/viz" if viz else "images/json"
        params = {
            'only_ids': 1 if quiet else 0,
            'all': 1 if all else 0,
            'params': name
        }

        return self.request(treq.get, host, path,
                            params=params,
                            expect_json=not viz)

    def containers(self, host,
                   quiet=False, all=False, trunc=True, latest=False,
                   since=None, before=None, limit=-1, pretty=False,
                   running=None, image=None):
        params = {
            'limit': 1 if latest else limit,
            'only_ids': 1 if quiet else 0,
            'all': 1 if all else 0,
            'trunc_cmd': 1 if trunc else 0,
            'since': since,
            'before': before
        }
        return self.get(host, 'containers/ps', params=params)

    def create_container(self, host, config, name=None):
        params = {}
        if name:
            params['name'] = name
        return self.post(
            host,
            "containers/create",
            params=params,
            data=config.to_json(),
            post_json=True)

    def inspect(self, host, container):
        return self.get(
            host, "containers/{}/json".format(container.id),
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

    def wait(self, host, container):
        """Waits for the container to stop and gets the exit code"""

        def log_results(results):
            self.log.debug("{0} has stopped with exit code {1}".format(
                container, results['StatusCode']))
            return results

        d = self.post(
            host, "containers/{}/wait".format(container.id),
            expect_json=True)

        d.addCallback(log_results)
        return d

    def request(self, method, host, path, **kwargs):

        kwargs = copy(kwargs)
        kwargs['params'] = _remove_empty(kwargs.get('params'))
        kwargs['pool'] = self.pool

        post_json = kwargs.pop('post_json', False)
        if post_json:
            headers = kwargs.setdefault('headers', {})
            headers['Content-Type'] = ['application/json']
            kwargs['data'] = json.dumps(kwargs['data'])

        kwargs['url'] = self._make_url(host.url, path)
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

    def get(self, host, path, **kwargs):
        return self.request(treq.get, host, path, **kwargs)

    def post(self, host, path, **kwargs):
        return self.request(treq.post, host, path, **kwargs)

    def delete(self, host, path, **kwargs):
        return self.request(treq.post, host, path, **kwargs)

    def _make_url(self, url, method):
        return "{}/v{}/{}".format(url, self.version, method)


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
