# most if this was taken from
# https://github.com/DataDog/dd-agent/blob/76459c8e97aa2c31599b0d78b07b3ecca45c19b4/checks.d/docker.py

DEFAULT_SOCKET_TIMEOUT = 15

import httplib
import socket
class UnixHTTPConnection(httplib.HTTPConnection):
    socket_timeout = DEFAULT_SOCKET_TIMEOUT
    def __init__(self, unix_socket):
        self._unix_socket = unix_socket
    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._unix_socket)
        sock.settimeout(self.socket_timeout)
        self.sock = sock
    def __call__(self, *args, **kwargs):
        httplib.HTTPConnection.__init__(self, *args, **kwargs)
        return self


import urllib2
from urlparse import urlsplit
import os
class UnixSocketHandler(urllib2.AbstractHTTPHandler):
    def unix_open(self, req):
        full_path = "%s%s" % urlsplit(req.get_full_url())[1:3]
        path = os.path.sep
        for part in full_path.split("/"):
            path = os.path.join(path, part)
            if not os.path.exists(path):
                break
            unix_socket = path
        # add a host or else urllib2 complains
        url = req.get_full_url().replace(unix_socket, "/localhost")
        new_req = urllib2.Request(url, req.get_data(), dict(req.header_items()))
        new_req.timeout = req.timeout
        return self.do_open(UnixHTTPConnection(unix_socket), new_req)
    unix_request = urllib2.AbstractHTTPHandler.do_request_


from checks import AgentCheck
from datetime import datetime
from subprocess import call
from collections import defaultdict
import urllib
from util import json
class DockerDaemonGauge(AgentCheck):
    def __init__(self, name, init_config, agentConfig, instances=None):
        AgentCheck.__init__(self, name, init_config, agentConfig, instances)
        # Initialize a HTTP opener with Unix socket support
        socket_timeout = int(init_config.get('socket_timeout', 0)) \
                         or DEFAULT_SOCKET_TIMEOUT
        UnixHTTPConnection.socket_timeout = socket_timeout
        self.url_opener = urllib2.build_opener(UnixSocketHandler())

    def check(self, instance):
        start = datetime.now()
        self._get_json("%(url)s/containers/json" % instance)
        end = datetime.now()
        time_msec = (end - start).total_seconds() * 1000
        self.gauge('docker.daemon.response_time', time_msec)

    def _get_json(self, uri, params=None, multi=False):
        """Utility method to get and parse JSON streams."""
        if params:
            uri = "%s?%s" % (uri, urllib.urlencode(params))
        self.log.debug("Connecting to Docker API at: %s" % uri)
        req = urllib2.Request(uri, None)
        try:
            request = self.url_opener.open(req)
        except urllib2.URLError, e:
            if "Errno 13" in str(e):
                raise Exception("Unable to connect to socket. dd-agent user "
                                "must be part of the 'docker' group")
            raise
        response = request.read()
        # Some Docker API versions occassionally send newlines in responses
        response = response.replace('\n', '')
        self.log.debug('Docker API response: %s', response)
        # docker api sometimes returns juxtaposed json dictionaries
        if multi and "}{" in response:
            response = "[{0}]".format(response.replace("}{", "},{"))
        if not response:
            return []
        try:
            return json.loads(response)
        except Exception as e:
            self.log.error('Failed to parse Docker API response: %s', response)
            raise DockerJSONDecodeError
