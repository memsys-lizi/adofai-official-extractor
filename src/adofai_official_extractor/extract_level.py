from __future__ import annotations

from .converter import main
from .extract_2x import HOOKS as HOOKS_2X
from .extract_3x import HOOKS as HOOKS_3X


if __name__ == "__main__":
    main(hooks_by_level={"2-X": HOOKS_2X, "3-X": HOOKS_3X})
