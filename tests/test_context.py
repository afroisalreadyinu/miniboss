import unittest

import pytest

from drillmaster.context import _Context, ContextError

class ContextTests(unittest.TestCase):

    def test_extrapolate(self):
        context = _Context(blah=123, yada="hello")
        output = context.extrapolate("Say {yada} to {blah}")
        assert output == "Say hello to 123"

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
        output = context.extrapolate_values({'key1': 'This is {blah}',
                                             'key2': 'And this is {yada}'})
        assert output == {'key1': 'This is 123',
                          'key2': 'And this is hello'}
