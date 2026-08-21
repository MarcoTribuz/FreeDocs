"""Text normalisation shared by everything that matches prose against a table.

One function, because two copies of it are two answers to the same question. The
context tables in ``detect/keywords.py`` and the clause patterns in
``detect/suppress.py`` are both written unaccented, and both are matched against
text a real French or German document wrote with the accents on.
"""

from __future__ import annotations

import unicodedata


def fold_diacritics(text: str) -> str:
    """Casefold and strip combining marks, so one spelling of a phrase is enough.

    Prevents a table written ``numero de tva`` from missing the ``numéro de TVA``
    the document actually contains. Decomposition is NFKD rather than NFD so the
    compatibility forms turn into their plain equivalents too — a document that
    carries a full-width or ligatured spelling is still the same phrase.

    Never use the result to index back into ``text``: folding changes length
    (``ß`` casefolds to ``ss``, ``é`` loses a character) so offsets do not
    survive it. Every caller here asks a yes-or-no question about a window and
    takes its offsets from elsewhere.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
