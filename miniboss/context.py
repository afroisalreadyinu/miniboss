import json
import pathlib
import logging

from miniboss.exceptions import ContextError

logger = logging.getLogger(__name__)

class _Context(dict):

    def save_to(self, directory):
        path = pathlib.Path(directory) / ".miniboss-context"
        with open(path, 'w') as context_file:
            context_file.write(json.dumps(self))

    def load_from(self, directory):
        path = pathlib.Path(directory) / ".miniboss-context"
        try:
            with open(path, 'r') as context_file:
                new_data = json.load(context_file)
            self.update(**new_data)
        except FileNotFoundError:
            logger.info("No miniboss context file in %s", directory)

    def remove_file(self, directory):
        path = pathlib.Path(directory) / ".miniboss-context"
        try:
            path.unlink()
        except FileNotFoundError:
            logger.info("No miniboss context file in %s", directory)

    def extrapolate(self, env_value):
        if not hasattr(env_value, "format"):
            return env_value
        try:
            return env_value.format(**self)
        except KeyError:
            raise ContextError("Could not extrapolate string '{}', existing keys: {}".format(
                env_value, ",".join(self.keys())))
        except ValueError:
            # This happens when there is a type mismatch
            raise ContextError("Could not extrapolate string '{}' due to type mismatch".format(env_value))
        except IndexError:
            raise ContextError("Only keyword argument extrapolation allowed, violating string: '{}'".format(env_value))

    def extrapolate_values(self, a_dict):
        return {key: self.extrapolate(value) for key,value in a_dict.items()}

    def _reset(self):
        # Used only for testing
        for key in list(self.keys()):
            self.pop(key)

Context = _Context()
