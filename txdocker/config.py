import json
import shlex

def parse_ports(vals):
    """
    Parses ports from format "hostPort:containerPort"
    into ExposedPorts and PortBindings tuples
    """
    exposed = {}
    bindings = {}

    for pair in vals:
        ports = pair.split(":")
        if len(ports) != 2:
            raise ValueError("Unspported format")

        host_port, container_port = ports
        if "/" in container_port:
            with_protocol = container_port.split("/")
            if len(with_protocol) != 2:
                raise ValueError("Unspported format")
            container_port, protocol = with_protocol
        else:
            protocol = "tcp"

        container_key = "{}/{}".format(container_port, protocol)
        exposed[container_key] = {}
        bindings.setdefault(container_key, []).append(
            {"HostIp": "", "HostPort": host_port})

    return (exposed, bindings)


class ContainerConfig(dict):
    """Container configuration helper.
    """
    def __init__(self, image, command='', **kwargs):
        dict.__init__(self)
        self.host = None

        if isinstance(command, str):
            command = shlex.split(command)

        get = kwargs.get
        exposed_ports, _ = parse_ports(get('ports', []))
        self.update({
            'Hostname': get('hostname'),
            'ExposedPorts': exposed_ports,
            'User': get('user'),
            'Tty': get('tty', False),
            'OpenStdin': get('open_stdin', False),
            'Memory': get('mem_limit', 0),
            'AttachStdin': get('stdin', False),
            'AttachStdout': get('stdout', False),
            'AttachStderr': get('stderr', False),
            'Env': get('environment'),
            'Cmd': command,
            'Dns': get('dns'),
            'Image': image,
            'Volumes': get('volumes'),
            'VolumesFrom': get('volumes_from'),
            'StdinOnce': get('stdin_once', False)
        })

        for key, val in self.items():
            if val is None:
                del self[key]
