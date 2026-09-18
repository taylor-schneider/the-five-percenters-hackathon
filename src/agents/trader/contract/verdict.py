"""The agent's recommendation, shared by both contract layers."""

from __future__ import annotations

from typing import Literal

#: proceed = do it. caution = defensible but carries a live risk the GM must
#: accept knowingly. do_not_proceed = the agent recommends against it, whether
#: or not the rules allow it. A rule-invalid trade is always do_not_proceed;
#: a rule-valid trade can still earn one.
Verdict = Literal["proceed", "proceed_with_caution", "do_not_proceed"]
