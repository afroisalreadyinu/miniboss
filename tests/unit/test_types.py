import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

from miniboss import types
from miniboss.exceptions import MinibossException


class GroupNameTests(unittest.TestCase):
    def setUp(self):
        types._unset_group_name()
        self.workdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.workdir)

    def test_set_group_name(self):
        types.set_group_name("test-group")
        assert types.group_name == "test-group"

    def test_error_on_group_name_reset(self):
        types.set_group_name("test-group")
        with pytest.raises(MinibossException) as context:
            types.set_group_name("test-group")

    def test_update_group_name(self):
        workdir = Path(self.workdir) / "some weird dir"
        types.update_group_name(workdir)
        assert types.group_name == "some-weird-dir"

    def test_update_group_name_existing_stays(self):
        types.set_group_name("test-group")
        workdir = Path(self.workdir) / "some weird dir"
        types.update_group_name(workdir)
        assert types.group_name == "test-group"
