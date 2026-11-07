"""System configuration package.

Provides test/parameter configuration schemas (``test_config``,
``treadmill_config``, ``param_schema``) and validation helpers used across the
application.

This is a regular package, distinct from ``agent.config``. Start application
modules from the project root with ``python -m`` (including ``agent.worker``)
so their imports use the same package hierarchy.
"""
