import os
import click

from miniboss import services
from miniboss.exceptions import MinibossCLIError

@click.group()
def cli():
    pass

def get_main_directory():
    """Return the path to the directory where the main script is located. If the cli
    function is being called from a Python shell, this function will raise an
    exception. """
    # pylint: disable=import-outside-toplevel
    import __main__
    if not hasattr(__main__, '__file__'):
        raise MinibossCLIError("Please call miniboss.cli from a Python script")
    return os.path.dirname(os.path.abspath(__main__.__file__))


@cli.command()
@click.option("--exclude", help="Names of services to exclude (comma-separated)")
@click.option("--network-name", help="Network name (generated from group name if not specified)")
@click.option("--timeout", type=int, default=300, help="Timeout for starting a service (seconds)")
def start(exclude, network_name, timeout):
    exclude = exclude.split(",") if exclude else []
    services.start_services(get_main_directory(), exclude, network_name, timeout)


@cli.command()
@click.option("--exclude", help="Names of services to exclude (comma-separated)")
@click.option("--network-name", help="Network name (generated from group name if not specified)")
@click.option("--remove", is_flag=True, default=False, help="Remove container images and network")
@click.option("--timeout", type=int, default=50, help="Timeout for stopping a service (seconds)")
def stop(exclude, network_name, remove, timeout):
    exclude = exclude.split(",") if exclude else []
    services.stop_services(get_main_directory(), exclude, network_name, remove, timeout)

@cli.command()
@click.option("--network-name", help="Network name (generated from group name if not specified)")
@click.option("--timeout", type=int, default=50, help="Timeout for stopping a service (seconds)")
@click.option("--remove", is_flag=True, default=False, help="Remove stopped container")
@click.argument('service')
def reload(service, network_name, timeout, remove):
    services.reload_service(get_main_directory(), service, network_name, remove, timeout)
