import logging
import os
import platform
import ssl
import sys
import typing

import click

import uvicontainer
from uvicontainer.typing import ProtocolFactory
from uvicontainer.config import (
    LOG_LEVELS,
    LOGGING_CONFIG,
    LOOP_SETUPS,
    SSL_PROTOCOL_VERSION,
    SERVER_CLASSES,
    Config,
)
from uvicontainer.server import TCPServer, UDPServer, BaseServer, ServerState  # noqa: F401  # Used to be defined here.
from uvicontainer.importer import import_from_string
from uvicontainer.supervisors import ChangeReload, Multiprocess

LEVEL_CHOICES = click.Choice(list(LOG_LEVELS.keys()))

LOOP_CHOICES = click.Choice([key for key in LOOP_SETUPS.keys() if key != "none"])

logger = logging.getLogger("uvicontainer.error")


def print_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(
        "Running uvicontainer %s with %s %s on %s"
        % (
            uvicontainer.__version__,
            platform.python_implementation(),
            platform.python_version(),
            platform.system(),
        )
    )
    ctx.exit()


@click.command()
@click.argument("protocol_factory")
@click.option(
    "--host",
    type=str,
    default="127.0.0.1",
    help="Bind socket to this host.",
    show_default=True,
)
@click.option(
    "--port",
    type=int,
    default=8000,
    help="Bind socket to this port.",
    show_default=True,
)
@click.option("--uds", type=str, default=None, help="Bind to a UNIX domain socket.")
@click.option(
    "--fd", type=int, default=None, help="Bind to socket from this file descriptor."
)
@click.option("--type", type=str, default="tcp", help="TCP or UDP", show_default=True)
@click.option(
    "--debug", is_flag=True, default=False, help="Enable debug mode.", hidden=True
)
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload.")
@click.option(
    "--reload-dir",
    "reload_dirs",
    multiple=True,
    help="Set reload directories explicitly, instead of using the current working"
         " directory.",
    type=click.Path(exists=True)
)
@click.option(
    "--reload-include",
    "reload_includes",
    multiple=True,
    help="Set glob patterns to include while watching for files. Includes '*.py' "
         "by default, which can be overridden in reload-excludes.",
)
@click.option(
    "--reload-exclude",
    "reload_excludes",
    multiple=True,
    help="Set glob patterns to exclude while watching for files. Includes "
         "'.*, .py[cod], .sw.*, ~*' by default, which can be overridden in reload-excludes.",
)
@click.option(
    "--reload-delay",
    type=float,
    default=0.25,
    show_default=True,
    help="Delay between previous and next check if application needs to be."
         " Defaults to 0.25s.",
)
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of worker processes. Defaults to the $WEB_CONCURRENCY environment"
         " variable if available, or 1. Not valid with --reload.",
)
@click.option(
    "--loop",
    type=LOOP_CHOICES,
    default="auto",
    help="Event loop implementation.",
    show_default=True,
)
@click.option(
    "--on-tick",
    type=str,
    default=None,
    help="Called Once per 0.1s, to update server state",
    show_default=True,
)
@click.option(
    "--on-startup",
    type=str,
    default=None,
    help="Do sth. before server start",
    show_default=True,
)
@click.option(
    "--on-shutdown",
    type=str,
    default=None,
    help="Do sth. after server shutdown such as resource recycle",
    show_default=True,
)
@click.option(
    "--env-file",
    type=click.Path(exists=True),
    default=None,
    help="Environment configuration file.",
    show_default=True,
)
@click.option(
    "--log-config",
    type=click.Path(exists=True),
    default=None,
    help="Logging configuration file. Supported formats: .ini, .json, .yaml.",
    show_default=True,
)
@click.option(
    "--log-level",
    type=LEVEL_CHOICES,
    default=None,
    help="Log level. [default: info]",
    show_default=True,
)
@click.option(
    "--access-log/--no-access-log",
    is_flag=True,
    default=True,
    help="Enable/Disable access log.",
)
@click.option(
    "--use-colors/--no-use-colors",
    is_flag=True,
    default=None,
    help="Enable/Disable colorized logging.",
)
@click.option(
    "--backlog",
    type=int,
    default=2048,
    help="Maximum number of connections to hold in backlog",
)
@click.option(
    "--ssl-keyfile", type=str, default=None, help="SSL key file", show_default=True
)
@click.option(
    "--ssl-certfile",
    type=str,
    default=None,
    help="SSL certificate file",
    show_default=True,
)
@click.option(
    "--ssl-keyfile-password",
    type=str,
    default=None,
    help="SSL keyfile password",
    show_default=True,
)
@click.option(
    "--ssl-version",
    type=int,
    default=SSL_PROTOCOL_VERSION,
    help="SSL version to use (see stdlib ssl module's)",
    show_default=True,
)
@click.option(
    "--ssl-cert-reqs",
    type=int,
    default=ssl.CERT_NONE,
    help="Whether client certificate is required (see stdlib ssl module's)",
    show_default=True,
)
@click.option(
    "--ssl-ca-certs",
    type=str,
    default=None,
    help="CA certificates file",
    show_default=True,
)
@click.option(
    "--ssl-ciphers",
    type=str,
    default="TLSv1",
    help="Ciphers to use (see stdlib ssl module's)",
    show_default=True,
)
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Display the uvicontainer version and exit.",
)  # todo 不再需要了
def main(
        protocol_factory: str,
        host: str,
        port: int,
        uds: str,
        fd: int,
        type: str,
        loop: str,
        on_tick: typing.Union[typing.Callable[[BaseServer, int], typing.Any], str],
        on_startup: typing.Union[typing.Callable[[BaseServer], typing.Any], str],
        on_shutdown: typing.Union[typing.Callable[[BaseServer], typing.Any], str],
        debug: bool,
        reload: bool,
        reload_dirs: typing.List[str],
        reload_includes: typing.List[str],
        reload_excludes: typing.List[str],
        reload_delay: float,
        workers: int,
        env_file: str,
        log_config: str,
        log_level: str,
        access_log: bool,
        backlog: int,
        ssl_keyfile: str,
        ssl_certfile: str,
        ssl_keyfile_password: str,
        ssl_version: int,
        ssl_cert_reqs: int,
        ssl_ca_certs: str,
        ssl_ciphers: str,
        use_colors: bool
) -> None:
    kwargs = {
        "host": host,
        "port": port,
        "uds": uds,
        "fd": fd,
        "type": type,
        "loop": loop,
        "on_tick": on_tick,
        "on_startup": on_startup,
        "on_shutdown": on_shutdown,
        "env_file": env_file,
        "log_config": LOGGING_CONFIG if log_config is None else log_config,
        "log_level": log_level,
        "access_log": access_log,
        "debug": debug,
        "reload": reload,
        "reload_dirs": reload_dirs if reload_dirs else None,
        "reload_includes": reload_includes if reload_includes else None,
        "reload_excludes": reload_excludes if reload_excludes else None,
        "reload_delay": reload_delay,
        "workers": workers,
        "backlog": backlog,
        "ssl_keyfile": ssl_keyfile,
        "ssl_certfile": ssl_certfile,
        "ssl_keyfile_password": ssl_keyfile_password,
        "ssl_version": ssl_version,
        "ssl_cert_reqs": ssl_cert_reqs,
        "ssl_ca_certs": ssl_ca_certs,
        "ssl_ciphers": ssl_ciphers,
        "use_colors": use_colors,
    }  # todo 添加 refresh_serverstate 表示刷新的间隔
    run(protocol_factory, **kwargs)


def run(protocol_factory: typing.Union[ProtocolFactory, str], **kwargs: typing.Any) -> None:
    config = Config(protocol_factory, **kwargs)
    server_class = SERVER_CLASSES.get(config.type)
    if server_class is None:
        server_class = import_from_string(config.type)  # A custom server class
    else:
        server_class = import_from_string(server_class)

    server = server_class(config=config)

    logger = logging.getLogger("uvicontainer.error")
    if (config.reload or config.workers > 1) and not isinstance(protocol_factory, str):
        logger.warning(
            "You must pass the protocol_factory as an import string to enable 'reload' or "
            "'workers'."
        )
        sys.exit(1)

    if config.should_reload:
        sock = config.bind_socket()
        ChangeReload(config, target=server.run, sockets=[sock]).run()
    elif config.workers > 1:
        sock = config.bind_socket()
        Multiprocess(config, target=server.run, sockets=[sock]).run()
    else:
        server.run()
    if config.uds:
        os.remove(config.uds)


if __name__ == "__main__":
    main()  # pragma: no cover
