import click

from drillmaster import services

@click.group()
def cli():
    pass

@cli.command()
@click.option("--use_existing", default=True, help="Use existing containers")
@click.option("--exclude", help="Names of services to exclude (comma-separated)")
@click.option("--network-name", default="drillmaster", help="Network to use")
def start(use_existing, exclude, network_name):
    services.start_services(use_existing, exlude, network_name)


@cli.command()
@click.option("--exclude", help="Names of services to exclude (comma-separated)")
@click.option("--purge", default=False, help="Remove container images and network")
def stop(exclude, service_definition_file):
    for container in containers.values():
        d.api.stop(container)
        d.api.remove_container(container)
