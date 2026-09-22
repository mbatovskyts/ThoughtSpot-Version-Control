"""Stage 1: Load and validate org config."""
import os
import sys
import yaml


class ConfigError(Exception):
    pass


ALLOWED_DEPENDENCY_MODES = {"include", "skip_if_exists", "require_tagged"}


def load_and_validate_config(config_path: str) -> dict:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    org_key = cfg.get("org_key", "").strip()
    if not org_key:
        raise ConfigError("org_key is required")

    migration_tag = cfg.get("migration_tag", "").strip()
    if not migration_tag:
        raise ConfigError("migration_tag is required and must be non-empty")
    # Naming convention (<org_key>_readyformigration) is recommended but not enforced,
    # so that custom tag names like 'Github_ReadyForMigration' are accepted.

    source = cfg.get("source", {})
    target = cfg.get("target", {})
    src_url = str(source.get("base_url", "")).rstrip("/")
    tgt_url = str(target.get("base_url", "")).rstrip("/")
    src_org = source.get("org_id")
    tgt_org = target.get("org_id")

    if not src_url:
        raise ConfigError("source.base_url is required")
    if not tgt_url:
        raise ConfigError("target.base_url is required")
    if src_org is None:
        raise ConfigError("source.org_id is required")
    if tgt_org is None:
        raise ConfigError("target.org_id is required")

    # Same cluster AND same org would mean migrating to itself — never allowed.
    if src_url == tgt_url and int(src_org) == int(tgt_org):
        raise ConfigError(
            "source and target are identical (same base_url and same org_id); "
            "same-cluster migrations require different org_ids"
        )

    dep_mode = cfg.get("dependency_mode", "include")
    if dep_mode not in ALLOWED_DEPENDENCY_MODES:
        raise ConfigError(
            f"dependency_mode '{dep_mode}' is not valid; "
            f"must be one of: {sorted(ALLOWED_DEPENDENCY_MODES)}"
        )

    variables = cfg.get("variables", {})
    db_var = variables.get("database", {})
    schema_var = variables.get("schema", {})

    # Hard stop: TABLE_MAPPING variables must have target_value configured.
    # (Empty string is treated as unconfigured for safety.)
    if not db_var.get("target_value"):
        raise ConfigError(
            "variables.database.target_value is required; "
            "set the target database name to prevent source values reaching prod"
        )
    if not schema_var.get("target_value"):
        raise ConfigError(
            "variables.schema.target_value is required; "
            "set the target schema name to prevent source values reaching prod"
        )

    return cfg


def main():
    org_key = os.environ.get("ORG_KEY")
    if not org_key:
        print("::error::ORG_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    config_path = f"config/orgs/{org_key}.yml"
    if not os.path.exists(config_path):
        print(f"::error::Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = load_and_validate_config(config_path)
        print(f"Config valid for org '{cfg['org_key']}' (tag: {cfg['migration_tag']})")
    except ConfigError as e:
        print(f"::error::Config validation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
