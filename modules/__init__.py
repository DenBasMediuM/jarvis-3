from __future__ import annotations

from modules.cash_journal.module import CashJournalModule
from modules.gincore.module import GincoreModule


def load_modules() -> list:
    """Register built-in modules. External language modules can be added later."""
    return [GincoreModule(), CashJournalModule()]
