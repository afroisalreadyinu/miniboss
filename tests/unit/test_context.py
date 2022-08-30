import json
import os
import tempfile
import unittest

import pytest

from miniboss.context import ContextError, _Context


class ContextTests(unittest.TestCase):
    def test_extrapolate(self):
        context = _Context(blah=123, yada="hello")
        output = context.extrapolate("Say {yada} to {blah}")
        assert output == "Say hello to 123"

    def test_extrapolate_nonstring(self):
        context = _Context(blah=123, yada="hello")
        assert 20 == context.extrapolate(20)

    def test_extrapolate_key_missing(self):
        context = _Context(blah=123, yada="hello")
        with pytest.raises(ContextError):
            context.extrapolate("Say {hello} to {blah}")

    def test_extrapolate_index_error(self):
        context = _Context(blah=123, yada="hello")
        with pytest.raises(ContextError):
            context.extrapolate("Say {} to {blah}")

    def test_extrapolate_type_mismatch(self):
        context = _Context(blah=123, yada="hello")
        with pytest.raises(ContextError):
            context.extrapolate("Say {blah:s} to {yada}")

    def test_extrapolate_values(self):
        context = _Context(blah=123, yada="hello")
        output = context.extrapolate_values(
            {"key1": "This is {blah}", "key2": "And this is {yada}", "key3": 456}
        )
        assert output == {
            "key1": "This is 123",
            "key2": "And this is hello",
            "key3": 456,
        }

    def test_save_to_load_from(self):
        directory = tempfile.mkdtemp()
        context = _Context(blah=123, yada="hello")
        context.save_to(directory)
        path = os.path.join(directory, ".miniboss-context")
        assert os.path.exists(path)
        with open(path, "r") as in_file:
            data = json.load(in_file)
        assert data == {"blah": 123, "yada": "hello"}
        new_context = _Context()
        new_context.load_from(directory)
        assert new_context["blah"] == 123
        assert new_context["yada"] == "hello"

    def test_load_from_missing(self):
        context = _Context()
        context.load_from("/not/existing/directory/blahakshdakusdhau")

    def test_remove_file(self):
        directory = tempfile.mkdtemp()
        context = _Context(blah=123, yada="hello")
        context.save_to(directory)
        path = os.path.join(directory, ".miniboss-context")
        assert os.path.exists(path)
        context.remove_file(directory)
        assert not os.path.exists(path)

    def test_remove_file_missing(self):
        context = _Context()
        context.remove_file("/not/existing/directory/blahakshdakusdhau")
