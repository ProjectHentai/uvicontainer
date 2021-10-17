import asyncio
import inspect
import json
import logging
import logging.config
import os
import socket
import ssl
import sys
from typing import List, Tuple, Union, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from uvicontainer.server import BaseServer

if sys.version_info < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

import click

try:
    import yaml
except ImportError:
    # If the code below that depends on yaml is exercised, it will raise a NameError.
    # Install the PyYAML package or the uvicontainer[standard] optional dependencies to
    # enable this functionality.
    pass

from uvicontainer.importer import ImportFromStringError, import_from_string

TRACE_LOG_LEVEL = 5

LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": TRACE_LOG_LEVEL,
}
LOOP_SETUPS = {
    "none": None,
    "auto": "uvicontainer.loops.auto:auto_loop_setup",
    "asyncio": "uvicontainer.loops.asyncio:asyncio_setup",
    "uvloop": "uvicontainer.loops.uvloop:uvloop_setup",
}
SERVER_CLASSES = {"tcp": "uvicontainer.server:TCPServer", "udp": "uvicontainer.server:UDPServer"}
# INTERFACES = ["auto", "asgi3", "asgi2", "wsgi"]

# Fallback to 'ssl.PROTOCOL_SSLv23' in order to support Python < 3.5.3.
SSL_PROTOCOL_VERSION = getattr(ssl, "PROTOCOL_TLS", ssl.PROTOCOL_SSLv23)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicontainer.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": None,
        },
        "access": {
            "()": "uvicontainer.logging.AccessFormatter",
            "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',  # noqa: E501
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicontainer": {"handlers": ["default"], "level": "INFO"},
        "uvicontainer.error": {"level": "INFO"},
        "uvicontainer.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}

logger = logging.getLogger("uvicontainer.error")


def create_ssl_context(
        certfile, keyfile, password, ssl_version, cert_reqs, ca_certs, ciphers
):
    ctx = ssl.SSLContext(ssl_version)
    get_password = (lambda: password) if password else None
    ctx.load_cert_chain(certfile, keyfile, get_password)
    ctx.verify_mode = cert_reqs
    if ca_certs:
        ctx.load_verify_locations(ca_certs)
    if ciphers:
        ctx.set_ciphers(ciphers)
    return ctx


class Config:
    def __init__(
            self,
            protocol_factory,
            host="127.0.0.1",
            port=8000,
            uds=None,
            fd=None,
            type: Union[str, Type["BaseServer"]] = "tcp",  # "xxx:bbb" is also ok
            loop="auto",
            on_tick=None,
            on_startup=None,
            on_shutdown=None,
            env_file=None,
            log_config=LOGGING_CONFIG,
            log_level=None,
            access_log=True,
            use_colors=None,
            debug=False,
            reload=False,
            reload_dirs=None,
            reload_delay=None,
            workers: int = None,
            backlog=2048,
            ssl_keyfile=None,
            ssl_certfile=None,
            ssl_keyfile_password=None,
            ssl_version=SSL_PROTOCOL_VERSION,
            ssl_cert_reqs=ssl.CERT_NONE,
            ssl_ca_certs=None,
            ssl_ciphers="TLSv1",
            **kwargs
    ):
        self.protocol_factory = protocol_factory
        self.host = host
        self.port = port
        self.uds = uds  # unix domain socket
        self.fd = fd
        self.type = type
        self.loop = loop
        self.on_tick = on_tick
        self.on_startup = on_startup
        self.on_shutdown = on_shutdown
        self.log_config = log_config
        self.log_level = log_level
        self.access_log = access_log
        self.use_colors = use_colors
        self.debug = debug
        self.reload = reload
        self.reload_delay = reload_delay or 0.25
        self.workers = workers or 1
        self.backlog = backlog
        self.ssl_keyfile = ssl_keyfile
        self.ssl_certfile = ssl_certfile
        self.ssl_keyfile_password = ssl_keyfile_password
        self.ssl_version = ssl_version
        self.ssl_cert_reqs = ssl_cert_reqs
        self.ssl_ca_certs = ssl_ca_certs
        self.ssl_ciphers = ssl_ciphers
        self.__dict__.update(kwargs)  # todo 也许可以装一些元数据
        # self.headers = headers if headers else []  # type: List[str]

        self.loaded = False
        self.configure_logging()

        if reload_dirs is None:
            self.reload_dirs = [os.getcwd()]
        else:
            if isinstance(reload_dirs, str):
                self.reload_dirs = [reload_dirs]
            else:
                self.reload_dirs = reload_dirs

        if env_file is not None:
            from dotenv import load_dotenv

            logger.info("Loading environment from '%s'", env_file)
            load_dotenv(dotenv_path=env_file)

        if workers is None and "CONCURRENCY" in os.environ:  # TODO note这里修改了
            self.workers = int(os.environ["CONCURRENCY"])

    # @property
    # def asgi_version(self) -> Union[Literal["2.0"], Literal["3.0"]]:
    #     return {"asgi2": "2.0", "asgi3": "3.0", "wsgi": "3.0"}[self.interface]

    @property
    def is_ssl(self) -> bool:
        return bool(self.ssl_keyfile or self.ssl_certfile)

    def configure_logging(self):
        logging.addLevelName(TRACE_LOG_LEVEL, "TRACE")

        if self.log_config is not None:
            if isinstance(self.log_config, dict):
                if self.use_colors in (True, False):
                    self.log_config["formatters"]["default"][
                        "use_colors"
                    ] = self.use_colors
                    self.log_config["formatters"]["access"][
                        "use_colors"
                    ] = self.use_colors
                logging.config.dictConfig(self.log_config)
            elif self.log_config.endswith(".json"):
                with open(self.log_config) as file:
                    loaded_config = json.load(file)
                    logging.config.dictConfig(loaded_config)
            elif self.log_config.endswith((".yaml", ".yml")):
                with open(self.log_config) as file:
                    loaded_config = yaml.safe_load(file)
                    logging.config.dictConfig(loaded_config)
            else:
                # See the note about fileConfig() here:
                # https://docs.python.org/3/library/logging.config.html#configuration-file-format
                logging.config.fileConfig(
                    self.log_config, disable_existing_loggers=False
                )

        if self.log_level is not None:
            if isinstance(self.log_level, str):
                log_level = LOG_LEVELS[self.log_level]
            else:
                log_level = self.log_level
            logging.getLogger("uvicontainer.error").setLevel(log_level)
            logging.getLogger("uvicontainer.access").setLevel(log_level)
            logging.getLogger("uvicontainer.asgi").setLevel(log_level)
        if self.access_log is False:
            logging.getLogger("uvicontainer.access").handlers = []
            logging.getLogger("uvicontainer.access").propagate = False

    def load(self):
        assert not self.loaded

        if self.is_ssl:
            self.ssl = create_ssl_context(
                keyfile=self.ssl_keyfile,
                certfile=self.ssl_certfile,
                password=self.ssl_keyfile_password,
                ssl_version=self.ssl_version,
                cert_reqs=self.ssl_cert_reqs,
                ca_certs=self.ssl_ca_certs,
                ciphers=self.ssl_ciphers,
            )
        else:
            self.ssl = None

        # self.lifespan_class = import_from_string(LIFESPAN[self.lifespan])
        try:
            self.loaded_protocol_factory = import_from_string(self.protocol_factory)
        except ImportFromStringError as exc:
            logger.error("Error loading protocol_factory. %s" % exc)
            sys.exit(1)

        if not callable(self.loaded_protocol_factory):
            logger.error("Error loading protocol_factory: not a Callable")
            sys.exit(1)
        self.loaded = True

    def setup_event_loop(self):
        loop_setup = import_from_string(LOOP_SETUPS[self.loop])
        if loop_setup is not None:
            loop_setup()

    def bind_socket(self) -> socket.socket:
        type_ = socket.SOCK_STREAM
        if self.type == "udp":
            type_ = socket.SOCK_DGRAM
        logger_args: List[Union[str, int]]
        if self.uds:
            path = self.uds
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(path)
                uds_perms = 0o666
                os.chmod(self.uds, uds_perms)
            except OSError as exc:
                logger.error(exc)
                sys.exit(1)

            message = "Uvicontainer running on unix socket %s (Press CTRL+C to quit)"
            sock_name_format = "%s"
            color_message = (
                    "Uvicontainer running on "
                    + click.style(sock_name_format, bold=True)
                    + " (Press CTRL+C to quit)"
            )
            logger_args = [self.uds]
        elif self.fd:
            sock = socket.fromfd(self.fd, socket.AF_UNIX, type_)
            message = "Uvicontainer running on socket %s (Press CTRL+C to quit)"
            fd_name_format = "%s"
            color_message = (
                    "Uvicontainer running on "
                    + click.style(fd_name_format, bold=True)
                    + " (Press CTRL+C to quit)"
            )
            logger_args = [sock.getsockname()]
        else:
            family = socket.AF_INET
            addr_format = "%s://%s:%d"

            if self.host and ":" in self.host:
                # It's an IPv6 address.
                family = socket.AF_INET6
                addr_format = "%s://[%s]:%d"

            sock = socket.socket(family=family, type=type_)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, self.port))
            except OSError as exc:
                logger.error(exc)
                sys.exit(1)

            message = f"Uvicontainer running on {addr_format} (Press CTRL+C to quit)"
            color_message = (
                    "Uvicontainer running on "
                    + click.style(addr_format, bold=True)
                    + " (Press CTRL+C to quit)"
            )
            protocol_name = "tcp + ssl" if self.is_ssl else "tcp"
            logger_args = [protocol_name, self.host, self.port]
        logger.info(message, *logger_args, extra={"color_message": color_message})
        sock.set_inheritable(True)
        return sock

    @property
    def should_reload(self):
        return isinstance(self.protocol_factory, str) and (self.debug or self.reload)
