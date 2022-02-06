import typing

from uvicontainer.supervisors.basereload import BaseReload
from uvicontainer.supervisors.multiprocess import Multiprocess

if typing.TYPE_CHECKING:
    ChangeReload: typing.Type[BaseReload]  # pragma: no cover
else:
    try:
        from uvicontainer.supervisors.watchgodreload import WatchGodReload as ChangeReload
    except ImportError:  # pragma: no cover
        from uvicontainer.supervisors.statreload import StatReload as ChangeReload

__all__ = ["Multiprocess", "ChangeReload"]
