# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared pytest fixtures for the Antigravity SDK test suite.

Parts of the SDK deliberately mutate process-global `logging` state. The most
consequential is `DebugConfig.apply_logging()`, which is invoked from an
`AgentConfig` pydantic model validator, so merely *constructing* a config with
`debug_config` enabled raises the `google.antigravity` logger to DEBUG for the
remainder of the interpreter's life.

That leak makes any test whose behavior depends on the ambient log level
order-dependent. `LiteRTConnectionStrategy._configure_litert_logging()` is one
such consumer: it selects the LiteRT C++ log severity by checking
`logging.getLogger("google.antigravity").isEnabledFor(logging.DEBUG)`, so a
config constructed by an earlier test silently flipped it from SILENT to
VERBOSE.

The autouse fixture below snapshots and restores logger levels around every
test so log-level mutations cannot escape the test that made them.

Note: this guard is pytest-specific. Tests that mutate logging state should
still clean up after themselves (e.g. via `addCleanup`) so they remain
isolated under other runners.
"""

import logging

import pytest

# Only the SDK's own logger tree and the root logger are guarded; leaving
# third-party logger levels alone keeps the fixture cheap and side-effect free.
_GUARDED_PREFIX = "google.antigravity"

_ROOT_KEY = ""


def _is_guarded(name: str) -> bool:
  return name == _GUARDED_PREFIX or name.startswith(_GUARDED_PREFIX + ".")


def _snapshot_levels() -> dict[str, int]:
  """Records the explicit level of the root logger and every SDK logger."""
  levels = {_ROOT_KEY: logging.getLogger().level}
  for name, logger in logging.Logger.manager.loggerDict.items():
    # loggerDict also holds PlaceHolder objects, which have no level.
    if isinstance(logger, logging.Logger) and _is_guarded(name):
      levels[name] = logger.level
  return levels


@pytest.fixture(autouse=True)
def restore_logging_levels():
  """Prevents per-test logging level changes from leaking into later tests."""
  before = _snapshot_levels()
  try:
    yield
  finally:
    logging.getLogger().setLevel(before[_ROOT_KEY])
    for name, level in before.items():
      if name != _ROOT_KEY:
        logging.getLogger(name).setLevel(level)
    # SDK loggers created during the test are reset to NOTSET so they inherit
    # from their parent instead of retaining a level the test assigned.
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
      if (
          isinstance(logger, logging.Logger)
          and _is_guarded(name)
          and name not in before
      ):
        logger.setLevel(logging.NOTSET)
