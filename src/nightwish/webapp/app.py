"""Compatibility shim for deploy configs that reference
`nightwish.webapp.app:app` (a leftover Railway start command).

Re-exports the MVP wiki app so a stale start command still serves the right
app. Canonical entrypoint remains `nightwish.mvp:app`.
"""

from nightwish.mvp import app  # noqa: F401
