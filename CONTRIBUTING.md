# Contributing

Install a normal wheel in a fresh environment. Run `python -m unittest discover -s tests -v`, `python examples/demo.py` and `python examples/contrast.py`. Tests must import the installed package; do not validate with editable installation or `PYTHONPATH`. Console paths come from the same interpreter's `sysconfig.get_path('scripts')`.

Add minimized synthetic reproducers, verify actual SQLite constraints/queries and unchanged source bytes, and use independent SQL oracles for equality changes rather than copied private helpers. Document unsupported cases; preserve equal/adverse contrast results and disclose competitor execution.

Replay history using `python tools/verify_history.py`. A correction cycle requires a concrete defect, direct-parent code correction, unchanged portable probe failing the before ordinary archive wheel and passing after, and actual logs. Feature chunks/test counts are not cycles. Record the exact executed commit; later tests cannot inherit older claims.

Never track private machine paths, credentials, real datasets or generated DBs. Use ignored `.artifacts/` for work. Contributions must be MIT compatible. Keep errors and supported behavior reliable before expanding scope.
