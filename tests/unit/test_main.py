import os
from unittest import TestCase, mock

from click.testing import CliRunner
from miniboss import main, types

class MainTests(TestCase):

    @mock.patch('miniboss.main.services')
    def test_start(self, mock_services):
        runner = CliRunner()
        result = runner.invoke(main.start)
        # There is something weird happening with __main__ depending on how
        # tests are executed, let's just skip that
        assert mock_services.start_services.call_count == 1
        args = mock_services.start_services.mock_calls[0][1]
        assert args[1:] == ([], None, 300)


    @mock.patch('miniboss.main.services')
    def test_start_args(self, mock_services):
        runner = CliRunner()
        result = runner.invoke(main.start, ['--network-name', 'yada', '--timeout', '20', '--exclude', 'testy'])
        # There is something weird happening with __main__ depending on how
        # tests are executed, let's just skip that
        assert mock_services.start_services.call_count == 1
        args = mock_services.start_services.mock_calls[0][1]
        assert args[1:] == (['testy'], 'yada', 20)


    @mock.patch('miniboss.main.services')
    def test_stop(self, mock_services):
        runner = CliRunner()
        result = runner.invoke(main.stop)
        assert mock_services.stop_services.call_count == 1
        args = mock_services.stop_services.mock_calls[0][1]
        assert args[1:] == ([], None, False, 50)


    @mock.patch('miniboss.main.services')
    def test_stop_args(self, mock_services):
        runner = CliRunner()
        result = runner.invoke(main.stop, ['--remove', '--timeout', '10',
                                           '--network-name', 'yada',
                                           '--exclude', 'testy'])
        assert mock_services.stop_services.call_count == 1
        args = mock_services.stop_services.mock_calls[0][1]
        assert args[1:] == (['testy'], 'yada', True, 10)

    @mock.patch('miniboss.main.services')
    def test_reload(self, mock_services):
        runner = CliRunner()
        result = runner.invoke(main.reload, ['testy'])
        assert mock_services.reload_service.call_count == 1
        args = mock_services.reload_service.mock_calls[0][1]
        assert args[1:] == ('testy', None, False, 50)


    @mock.patch('miniboss.main.services')
    def test_reload_args(self, mock_services):
        runner = CliRunner()
        result = runner.invoke(main.reload, ['testy', '--remove', '--timeout', '10',
                                             '--network-name', 'yada'])
        assert mock_services.reload_service.call_count == 1
        args = mock_services.reload_service.mock_calls[0][1]
        assert args[1:] == ('testy', 'yada', True, 10)
