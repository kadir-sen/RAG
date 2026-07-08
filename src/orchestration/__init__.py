"""Chat-native tool orchestration — composite intents rendered as blocks
inside normal assistant messages. The planner only matches registered
intents; the executor only dispatches whitelisted runners; every output type
has its own guard, and failed steps degrade to fallbacks without sinking the
safe blocks.
"""

from .executor import run_composite
from .registry import CAPABILITIES, COMPOSITE_INTENTS, match_composite

__all__ = ["run_composite", "match_composite", "COMPOSITE_INTENTS",
           "CAPABILITIES"]
