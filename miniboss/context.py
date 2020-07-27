from miniboss.exceptions import ContextError

class _Context(dict):

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

Context = _Context()
