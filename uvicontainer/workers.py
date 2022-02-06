import asyncio
import logging
import signal
import sys
from typing import Any

from gunicorn.arbiter import Arbiter
from gunicorn.workers.base import Worker

from uvicontainer.config import Config
from uvicontainer.main import TCPServer


class UvicontainerWorker(Worker):
    """
    A worker class for Gunicorn that interfaces with a protocol factory
    """

    CONFIG_KWARGS = {"loop": "auto"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        logger = logging.getLogger("uviconrainer.error")
        logger.handlers = self.log.error_log.handlers
        logger.setLevel(self.log.error_log.level)
        logger.propagate = False

        logger = logging.getLogger("uviconrainer.access")
        logger.handlers = self.log.access_log.handlers
        logger.setLevel(self.log.access_log.level)
        logger.propagate = False

        config_kwargs: dict = {
            "protocol_factory": None,
            "log_config": None,
            "timeout_keep_alive": self.cfg.keepalive,
            "timeout_notify": self.timeout,
            "limit_max_requests": self.max_requests,
            "forwarded_allow_ips": self.cfg.forwarded_allow_ips,
        }

        if self.cfg.is_ssl:
            ssl_kwargs = {
                "ssl_keyfile": self.cfg.ssl_options.get("keyfile"),
                "ssl_certfile": self.cfg.ssl_options.get("certfile"),
                "ssl_keyfile_password": self.cfg.ssl_options.get("password"),
                "ssl_version": self.cfg.ssl_options.get("ssl_version"),
                "ssl_cert_reqs": self.cfg.ssl_options.get("cert_reqs"),
                "ssl_ca_certs": self.cfg.ssl_options.get("ca_certs"),
                "ssl_ciphers": self.cfg.ssl_options.get("ciphers"),
            }
            config_kwargs.update(ssl_kwargs)

        if self.cfg.settings["backlog"].value:
            config_kwargs["backlog"] = self.cfg.settings["backlog"].value

        config_kwargs.update(self.CONFIG_KWARGS)

        self.config = Config(**config_kwargs)

    def init_process(self) -> None:
        self.config.setup_event_loop()
        super(UvicontainerWorker, self).init_process()

    def init_signals(self) -> None:
        # Reset signals so Gunicorn doesn't swallow subprocess return codes
        # other signals are set up by Server.install_signal_handlers()
        # See: https://github.com/encode/uvicontainer/issues/894
        for s in self.SIGNALS:
            signal.signal(s, signal.SIG_DFL)

    async def _serve(self) -> None:
        self.config.protocol_factory = self.wsgi
        server = TCPServer(config=self.config)
        await server.serve(sockets=self.sockets)
        if not server.started:
            sys.exit(Arbiter.WORKER_BOOT_ERROR)

    def run(self) -> None:
        async def all_():
            await asyncio.wait([self._serve(),
                                self.on_tick()], return_when=asyncio.FIRST_COMPLETED)

        if sys.version_info >= (3, 7):
            return asyncio.run(all_())
        return asyncio.get_event_loop().run_until_complete(all_())

    async def on_tick(self) -> None:
        while True:
            self.notify()
            await asyncio.sleep(self.timeout)
