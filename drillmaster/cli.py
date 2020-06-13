import click

from drillmaster import services

@click.group()
def cli():
    pass

@cli.command()
@click.option("--create-new", default=False, help="Create new containers instead of using existing")
@click.option("--exclude", help="Names of services to exclude (comma-separated)")
@click.option("--network-name", default="drillmaster-network", help="Network to use")
@click.option("--timeout", default="drillmaster-network", help="Network to use")
def start(create_new, exclude, network_name, timeout):
    services.start_services(use_existing, exlude, network_name, timeout)


@cli.command()
@click.option("--exclude", help="Names of services to exclude (comma-separated)")
@click.option("--purge", default=False, help="Remove container images and network")
def stop(exclude, service_definition_file):
    for container in containers.values():
        d.api.stop(container)
        d.api.remove_container(container)
