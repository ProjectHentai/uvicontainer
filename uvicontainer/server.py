import asyncio
import logging
import os
import platform
import signal
import socket
import sys
import threading
import abc
import time
from typing import TYPE_CHECKING, Any, List, Optional, Set, Tuple, Union
from email.utils import formatdate
from types import FrameType
import click

from uvicontainer.config import Config


# from uvicontainer._handlers.http import handle_http

# from uvicontainer.protocols.http.h11_impl import H11Protocol
# from uvicontainer.protocols.http.httptools_impl import HttpToolsProtocol
# from uvicontainer.protocols.websockets.websockets_impl import WebSocketProtocol
# from uvicontainer.protocols.websockets.wsproto_impl import WSProtocol


if sys.platform != "win32":
    from asyncio import start_unix_server as _start_unix_server
else:

    async def _start_unix_server(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Cannot start a unix server on win32")


HANDLED_SIGNALS = (
    signal.SIGINT,  # Unix signal 2. Sent by Ctrl+C.
    signal.SIGTERM,  # Unix signal 15. Sent by `kill <pid>`.
)

logger = logging.getLogger("uvicontainer.error")


class ServerState:
    """
    Shared servers state that is available between all protocol instances.
    """

    def __init__(self) -> None:
        self.total_requests = 0
        self.connections: Set[asyncio.Protocol] = set()
        self.tasks: Set[asyncio.Task] = set()
        self.default_headers: List[Tuple[bytes, bytes]] = []


class BaseServer(abc.ABC):
    """每个进程server容器"""

    def __init__(self, config: Config):  # todo 加入服务器启动和停止的hook 模拟asgi
        self.config = config
        self.started = False
        self.should_exit = False
        self.force_exit = False
        self.last_notified = 0.0

    def run(self, sockets: Optional[List[socket.socket]] = None) -> None:
        self.config.setup_event_loop()
        if sys.version_info >= (3, 7):
            return asyncio.run(self.serve(sockets=sockets))
        return asyncio.get_event_loop().run_until_complete(self.serve(sockets=sockets))

    async def serve(self, sockets: Optional[List[socket.socket]] = None) -> None:
        config = self.config
        if not config.loaded:
            config.load()
        self.install_signal_handlers()

        await self.startup(sockets=sockets)
        if self.should_exit:
            return
        await self.main_loop()
        await self.shutdown(sockets=sockets)

    async def startup(self, sockets: list = None):
        on_startup = self.config.on_startup
        if on_startup:
            ret = on_startup(self)
            if asyncio.iscoroutine(ret):
                await ret

    async def main_loop(self):
        counter = 0
        should_exit = await self.on_tick(counter)
        while not should_exit:
            counter += 1
            counter = counter % 864000
            await asyncio.sleep(0.1)
            should_exit = await self.on_tick(counter)

    async def on_tick(self, counter: int):
        """called once per 0.1s  if counter%10==0
        to check the server state
        """
        on_tick = self.config.on_tick
        if on_tick:
            ret = on_tick(self, counter)
            if asyncio.iscoroutine(ret):
                await ret
        if self.should_exit:
            return True
        return False

    async def shutdown(self, sockets: list = None):
        on_shutdown = self.config.on_shutdown
        if on_shutdown:
            ret = on_shutdown(self)
            if asyncio.iscoroutine(ret):
                await ret
        for sock in sockets or []:
            sock.close()

    def install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            # Signals can only be listened to from the main thread.
            return

        loop = asyncio.get_event_loop()

        try:
            for sig in HANDLED_SIGNALS:
                loop.add_signal_handler(sig, self.handle_exit, sig, None)
        except NotImplementedError:  # pragma: no cover
            # Windows
            for sig in HANDLED_SIGNALS:
                signal.signal(sig, self.handle_exit)

    def handle_exit(self, sig: signal.Signals, frame: FrameType):
        if self.should_exit:
            self.force_exit = True
        else:
            self.should_exit = True


class TCPServer(BaseServer):
    def __init__(self, config: Config):  # todo 加入服务器启动和停止的hook 模拟asgi
        super().__init__(config)
        self.servers = []
        self.server_state = ServerState()

    async def serve(self, sockets: list = None):
        process_id = os.getpid()
        message = "Started server process [%d]"
        color_message = "Started server process [" + click.style("%d", fg="cyan") + "]"
        logger.info(message, process_id, extra={"color_message": color_message})

        await super().serve(sockets=sockets)

        message = "Finished server process [%d]"
        color_message = "Finished server process [" + click.style("%d", fg="cyan") + "]"
        logger.info(message, process_id, extra={"color_message": color_message})

    async def startup(self, sockets: list = None) -> None:
        await super().startup(sockets)
        config = self.config
        loop = asyncio.get_event_loop()

        if sockets is not None:
            # Explicitly passed a list of open sockets.
            # We use this when the server is run from a Gunicorn worker.

            def _share_socket(sock: socket.SocketType) -> socket.SocketType:
                # Windows requires the socket be explicitly shared across
                # multiple workers (processes).
                from socket import fromshare  # type: ignore

                sock_data = sock.share(os.getpid())  # type: ignore
                return fromshare(sock_data)

            for sock in sockets:
                if config.workers > 1 and platform.system() == "Windows":
                    sock = _share_socket(sock)
                server = await loop.create_server(
                    config.loaded_protocol_factory, sock=sock, ssl=config.ssl, backlog=config.backlog
                )
                self.servers.append(server)
            listeners = sockets

        elif config.fd is not None:
            # Use an existing socket, from a file descriptor.
            sock = socket.fromfd(config.fd, socket.AF_UNIX, socket.SOCK_STREAM)
            server = await loop.create_server(
                config.loaded_protocol_factory, sock=sock, ssl=config.ssl, backlog=config.backlog
            )
            assert server.sockets is not None  # mypy
            listeners = server.sockets
            self.servers = [server]

        elif config.uds is not None:
            # Create a socket using UNIX domain socket.
            uds_perms = 0o666
            if os.path.exists(config.uds):
                uds_perms = os.stat(config.uds).st_mode
            server = await loop.create_unix_server(
                config.loaded_protocol_factory, path=config.uds, ssl=config.ssl, backlog=config.backlog
            )
            os.chmod(config.uds, uds_perms)
            assert server.sockets is not None  # mypy
            listeners = server.sockets
            self.servers = [server]

        else:
            # Standard case. Create a socket from a host/port pair.
            try:
                server = await loop.create_server(
                    config.loaded_protocol_factory,
                    host=config.host,
                    port=config.port,
                    ssl=config.ssl,
                    backlog=config.backlog,
                )
            except OSError as exc:
                logger.error(exc)
                sys.exit(1)
            assert server.sockets is not None  # mypy
            listeners = server.sockets
            self.servers = [server]

        if sockets is None:
            self._log_started_message(listeners)
        else:
            # We're most likely running multiple workers, so a message has already been
            # logged by `config.bind_socket()`.
            pass

        self.started = True

    def _log_started_message(self, listeners: List[socket.SocketType]) -> None:
        config = self.config

        if config.fd is not None:
            sock = listeners[0]
            logger.info(
                "Uvicontainer running on socket %s (Press CTRL+C to quit)",
                sock.getsockname(),
            )

        elif config.uds is not None:
            logger.info(
                "Uvicontainer running on unix socket %s (Press CTRL+C to quit)", config.uds
            )

        else:
            addr_format = "%s://%s:%d"
            host = "0.0.0.0" if config.host is None else config.host
            if ":" in host:
                # It's an IPv6 address.
                addr_format = "%s://[%s]:%d"

            port = config.port
            if port == 0:
                port = listeners[0].getsockname()[1]

            protocol_name = ""
            if config.is_ssl and config.type == "tcp":
                protocol_name += "ssl"
            protocol_name += config.type

            message = f"Uvicontainer running on {addr_format} (Press CTRL+C to quit)"
            color_message = (
                    "Uvicontainer running on "
                    + click.style(addr_format, bold=True)
                    + " (Press CTRL+C to quit)"
            )
            logger.info(
                message,
                protocol_name,
                host,
                port,
                extra={"color_message": color_message},
            )

    async def shutdown(self, sockets: Optional[List[socket.socket]] = None) -> None:
        logger.info("Shutting down")
        await super().shutdown(sockets)
        # Stop accepting new connections.
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()
        # Send the lifespan shutdown event, and wait for application shutdown.


class UDPServer(BaseServer):
    def __init__(self, config: Config):
        super().__init__(config)
        self.servers = []

    async def serve(self, sockets: list = None):
        process_id = os.getpid()

        message = "Started server process [%d]"
        color_message = "Started server process [" + click.style("%d", fg="cyan") + "]"
        logger.info(message, process_id, extra={"color_message": color_message})

        await super().serve(sockets=sockets)

        message = "Finished server process [%d]"
        color_message = "Finished server process [" + click.style("%d", fg="cyan") + "]"
        logger.info(
            "Finished server process [%d]",
            process_id,
            extra={"color_message": color_message},
        )

    async def startup(self, sockets: list = None) -> None:
        await super().startup(sockets)
        config = self.config
        loop = asyncio.get_event_loop()

        if sockets is not None:
            # Explicitly passed a list of open sockets.
            # We use this when the server is run from a Gunicorn worker.

            def _share_socket(sock: socket.SocketType) -> socket.SocketType:
                # Windows requires the socket be explicitly shared across
                # multiple workers (processes).
                from socket import fromshare  # type: ignore

                sock_data = sock.share(os.getpid())  # type: ignore
                return fromshare(sock_data)

            for sock in sockets:
                if config.workers > 1 and platform.system() == "Windows":
                    sock = _share_socket(sock)
                transport, protocol = await loop.create_datagram_endpoint(
                    config.loaded_protocol_factory, sock=sock
                )
                self.servers.append(protocol)
            listeners = sockets

        elif config.fd is not None:
            # Use an existing socket, from a file descriptor.
            sock = socket.fromfd(config.fd, socket.AF_UNIX, socket.SOCK_DGRAM)
            transport, protocol = await loop.create_datagram_endpoint(
                config.loaded_protocol_factory, sock=sock
            )
            assert transport._sock is not None  # mypy
            listeners = [transport._sock]
            self.servers = [protocol]

        elif config.uds is not None:
            # Create a socket using UNIX domain socket.
            raise ValueError("UDPServer can't be used with UNIX domain socket")
        else:
            # Standard case. Create a socket from a host/port pair.
            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    config.loaded_protocol_factory,
                    local_addr=(config.host, config.port)
                )
            except OSError as exc:
                logger.error(exc)
                sys.exit(1)
            assert transport._sock is not None  # mypy
            listeners = [transport._sock]
            self.servers = [protocol]

        if sockets is None:
            self._log_started_message(listeners)
        else:
            # We're most likely running multiple workers, so a message has already been
            # logged by `config.bind_socket()`.
            pass

        self.started = True

    async def shutdown(self, sockets: list = None):
        logger.info("Shutting down")
        await super().shutdown(sockets)
