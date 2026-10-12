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

"""Regression tests for debug-logging state isolation between tests.

`AgentConfig` applies `DebugConfig.apply_logging()` from a pydantic model
validator, so constructing a config with `debug_config` enabled raises the
`google.antigravity` logger to DEBUG process-wide and never restores it.

That leak previously made `litert_connection_test`'s
`test_litert_logging_defaults_to_silent` fail only when it ran after a test that
built a debug-enabled config: `_configure_litert_logging()` reads
`logging.getLogger("google.antigravity").isEnabledFor(logging.DEBUG)` and chose
VERBOSE instead of SILENT.

These tests pin both halves of the contract: the side effect itself (so a change
to it is a deliberate, visible decision) and the guarantee that it cannot escape
the test that triggered it.

The tests are module-level functions on purpose: pytest runs them in definition
order, whereas `unittest.TestCase` methods run alphabetically. The leak is only
observable across a test boundary, so the dirtying test must run first.
"""

import logging

from google.antigravity.connections import connection

_SDK_LOGGER_NAME = "google.antigravity"


class _ConcreteConfig(connection.AgentConfig):
  """Minimal concrete AgentConfig; the ABC cannot be instantiated directly."""

  def create_strategy(self, *, tool_runner, hook_runner):
    return None


def test_agent_config_with_debug_config_raises_sdk_logger_to_debug():
  """Documents the validator side effect that motivates the isolation guard."""
  sdk_logger = logging.getLogger(_SDK_LOGGER_NAME)
  assert not sdk_logger.isEnabledFor(logging.DEBUG), (
      "SDK logger was already DEBUG-enabled before this test ran, so an"
      " earlier test leaked logging state."
  )

  config = _ConcreteConfig(debug_config=True)

  assert config.debug_config is not None
  assert sdk_logger.level == logging.DEBUG
  # Deliberately not restored here: the next test asserts the suite-level guard
  # cleans it up.


def test_sdk_logger_level_does_not_leak_from_previous_test():
  """Regression guard: the DEBUG level set above must not survive."""
  sdk_logger = logging.getLogger(_SDK_LOGGER_NAME)

  assert not sdk_logger.isEnabledFor(logging.DEBUG), (
      "DEBUG leaked from a previous test. Any code branching on"
      f" logging.getLogger({_SDK_LOGGER_NAME!r}).isEnabledFor(logging.DEBUG)"
      " — e.g. LiteRT log-severity selection — becomes order-dependent."
  )


def test_explicit_sdk_logger_level_change_is_reverted_between_tests():
  """Dirties the SDK logger directly, mirroring apply_logging()'s effect."""
  logging.getLogger(_SDK_LOGGER_NAME).setLevel(logging.DEBUG)


def test_sdk_logger_level_restored_after_explicit_change():
  """Companion to the test above; asserts the explicit change was reverted."""
  assert not logging.getLogger(_SDK_LOGGER_NAME).isEnabledFor(logging.DEBUG)


def test_root_logger_level_change_is_reverted_between_tests():
  """The guard also covers the root logger, which gates effective levels."""
  logging.getLogger().setLevel(logging.DEBUG)


def test_root_logger_level_restored_after_explicit_change():
  """Companion to the test above; asserts the root level was reverted."""
  assert not logging.getLogger().isEnabledFor(logging.DEBUG)


def test_debug_config_apply_logging_honors_custom_level():
  """A custom logging_level is applied verbatim, not coerced to DEBUG."""
  connection.DebugConfig(logging_level=logging.WARNING).apply_logging()

  assert logging.getLogger(_SDK_LOGGER_NAME).level == logging.WARNING


def test_debug_config_apply_logging_noop_when_level_is_none():
  """`logging_level=None` leaves the SDK logger untouched."""
  sdk_logger = logging.getLogger(_SDK_LOGGER_NAME)
  before = sdk_logger.level

  connection.DebugConfig(logging_level=None).apply_logging()

  assert sdk_logger.level == before
