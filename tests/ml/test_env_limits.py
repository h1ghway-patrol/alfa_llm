import os
import unittest
from unittest import mock

from app.ml.llm.base import BaseLLM, apply_env_limits
from app.ml.llm.fake import FakeLLM


def env_without_limits(**extra):
    base = {k: v for k, v in os.environ.items() if k not in ("DAILY_TOKEN_LIMIT_TOKENS", "BUDGET_RUB")}
    base.update(extra)
    return mock.patch.dict(os.environ, base, clear=True)


class EnvLimitsTests(unittest.TestCase):
    def test_env_overrides_yaml(self):
        with env_without_limits(DAILY_TOKEN_LIMIT_TOKENS="1000", BUDGET_RUB="12.5"):
            cfg = BaseLLM().cfg
        self.assertEqual((cfg["daily_token_limit"], cfg["budget_rub"]), (1000, 12.5))

    def test_empty_env_keeps_yaml_values(self):
        with env_without_limits(DAILY_TOKEN_LIMIT_TOKENS="", BUDGET_RUB=""):
            cfg = BaseLLM().cfg
        self.assertIsNone(cfg["daily_token_limit"])
        self.assertEqual(cfg["budget_rub"], 500)

    def test_invalid_values_fail_with_readable_message(self):
        with env_without_limits(DAILY_TOKEN_LIMIT_TOKENS="много"):
            with self.assertRaises(ValueError) as cm:
                apply_env_limits({})
        self.assertIn("DAILY_TOKEN_LIMIT_TOKENS", str(cm.exception))
        with env_without_limits(BUDGET_RUB="abc"):
            with self.assertRaises(ValueError):
                apply_env_limits({})

    def test_zero_and_negative_rejected_like_in_api_config(self):
        for name, bad in (("DAILY_TOKEN_LIMIT_TOKENS", "0"), ("DAILY_TOKEN_LIMIT_TOKENS", "-5"),
                          ("BUDGET_RUB", "0"), ("BUDGET_RUB", "-1")):
            with env_without_limits(**{name: bad}):
                with self.assertRaises(ValueError, msg=f"{name}={bad}"):
                    apply_env_limits({})

    def test_explicit_config_is_not_touched_by_env(self):
        with env_without_limits(DAILY_TOKEN_LIMIT_TOKENS="5"):
            llm = FakeLLM()
        self.assertNotIn("daily_token_limit", llm.cfg)
