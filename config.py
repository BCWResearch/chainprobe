import toml

def load_config(path="config.toml"):
    with open(path, "r") as f:
        return toml.load(f)
