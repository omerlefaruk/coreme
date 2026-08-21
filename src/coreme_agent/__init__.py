"""Fleet agent: local SQLite queue (F1) or hub claim + hash pull (F3 --hub).

Sibling package to the kernel (``coreme``). Hub HTTP lives in ``coreme_hub``.
See ``docs/days/FLEET.md``.
"""

from __future__ import annotations

from coreme import __version__

__all__ = ["__version__"]
