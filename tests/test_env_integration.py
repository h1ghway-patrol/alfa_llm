import os
import unittest
from unittest import mock

from app.db import repositories as repo
from app.db.build import build
from app.db.connection import connect
from app.db.passwords import verify_password

ENV_KEYS = ("VIEWER_PASSWORD", "ADMIN_PASSWORD", "SEED_VIEWER_PASSWORD", "SEED_ADMIN_PASSWORD")


def clean_env(**extra):
    base = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    base.update(extra)
    return mock.patch.dict(os.environ, base, clear=True)


class SeedPasswordsTests(unittest.TestCase):
    def seeded(self, **env):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, clean_env(**env):
            db = str(Path(d) / "app.db")
            build(db)
            conn = connect(db)
            try:
                return {u: repo.get_user_by_username(conn, u) for u in ("viewer", "admin")}
            finally:
                conn.close()

    def test_defaults_match_env_example(self):
        users = self.seeded()
        self.assertTrue(verify_password("viewer-demo", users["viewer"]["password_hash"], users["viewer"]["salt"]))
        self.assertTrue(verify_password("admin-demo", users["admin"]["password_hash"], users["admin"]["salt"]))

    def test_api_variable_names_are_used(self):
        users = self.seeded(VIEWER_PASSWORD="v-secret", ADMIN_PASSWORD="a-secret")
        self.assertTrue(verify_password("v-secret", users["viewer"]["password_hash"], users["viewer"]["salt"]))
        self.assertTrue(verify_password("a-secret", users["admin"]["password_hash"], users["admin"]["salt"]))
        self.assertFalse(verify_password("viewer-demo", users["viewer"]["password_hash"], users["viewer"]["salt"]))

    def test_old_seed_names_still_work_and_new_names_win(self):
        users = self.seeded(SEED_VIEWER_PASSWORD="old")
        self.assertTrue(verify_password("old", users["viewer"]["password_hash"], users["viewer"]["salt"]))
        users = self.seeded(SEED_VIEWER_PASSWORD="old", VIEWER_PASSWORD="new")
        self.assertTrue(verify_password("new", users["viewer"]["password_hash"], users["viewer"]["salt"]))

    def test_empty_value_falls_back_to_default(self):
        users = self.seeded(VIEWER_PASSWORD="  ")
        self.assertTrue(verify_password("viewer-demo", users["viewer"]["password_hash"], users["viewer"]["salt"]))
