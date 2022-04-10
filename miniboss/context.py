import json
import pathlib
import logging
from typing import Any

from miniboss.exceptions import ContextError

logger = logging.getLogger(__name__)


class _Context(dict[str, Any]):
    filename = ".miniboss-context"

    def save_to(self, directory: str) -> None:
        path = pathlib.Path(directory) / self.filename
        with open(path, 'w', encoding='utf-8') as context_file:
            context_file.write(json.dumps(self))

    def load_from(self, directory: str) -> None:
        path = pathlib.Path(directory) / self.filename
        try:
            with open(path, 'r', encoding='utf-8') as context_file:
                new_data = json.load(context_file)
            self.update(**new_data)
        except FileNotFoundError:
            logger.info("No miniboss context file in %s", directory)

    def remove_file(self, directory: str) -> None:
        path = pathlib.Path(directory) / self.filename
        try:
            path.unlink()
        except FileNotFoundError:
            logger.info("No miniboss context file in %s", directory)

    def extrapolate(self, env_value: Any) -> Any:
        if not hasattr(env_value, "format"):
            return env_value
        try:
            return env_value.format(**self)
        except KeyError:
            keys = ",".join(self.keys())
            exc = ContextError(f"Could not extrapolate string '{env_value}', existing keys: {keys}")
            raise exc from None
        except ValueError:
            # This happens when there is a type mismatch
            exc = ContextError(f"Could not extrapolate string '{env_value}' due to type mismatch" )
            raise exc from None
        except IndexError:
            msg ="Only keyword argument extrapolation allowed, violating string: '{env_value}'"
            raise ContextError(msg) from None

    def extrapolate_values(self, a_dict: dict[str, Any]) -> dict[str, Any]:
        return {key: self.extrapolate(value) for key,value in a_dict.items()}

    def _reset(self) -> None:
        # Used only for testing
        for key in list(self.keys()):
            self.pop(key)

Context = _Context()
