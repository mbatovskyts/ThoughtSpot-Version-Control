#!/usr/bin/env python3
"""
Stage 1: Load and validate org config.

Reads config/orgs/<org_key>.yml, validates required fields, and
writes a validated config JSON for downstream stages.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml


def load_and_validate(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    errors = []

    org_key = cfg.get("org_key", "")
    if not org_key:
        errors.append("org_key is required")

    migration_tag = cfg.get("migration_tag", "")
    if migration_tag != f"{org_key}_readyformigration":
        errors.append(
            f"migration_tag must equal '{org_key}_readyformigration', got '{migration_tag}'"
        )

    source = cfg.get("source", {})
    target = cfg.get("target", {})
    src_url = source.get("base_url", "").rstrip("/")
    tgt_url = target.get("base_url", "").rstrip("/")
    src_org = source.get("org_id")
    tgt_org = target.get("org_id")

    if not src_url:
        errors.append("source.base_url is required")
    if not tgt_url:
        errors.append("target.base_url is required")
    if src_org is None:
        errors.append("source.org_id is required")
    if tgt_org is None:
        errors.append("target.org_id is required")

    if src_url and tgt_url and src_org is not None and tgt_org is not None:
        if src_url == tgt_url and int(src_org) == int(tgt_org):
            errors.append(
                "source and target are identical (same base_url AND same org_id). "
                "Same-cluster migration requires different org_ids."
            )

    dep_mode = cfg.get("dependency_mode", "include")
    if dep_mode not in ("include", "skip_if_exists", "require_tagged"):
        errors.append(f"dependency_mode must be include|skip_if_exists|require_tagged, got '{dep_mode}'")

    variables = cfg.get("variables", {})
    for field in ("database", "schema"):
        var = variables.get(field, {})
        if not var.get("ts_variable_name"):
            errors.append(f"variables.{field}.ts_variable_name is required")
        if not var.get("target_value"):
            errors.append(f"variables.{field}.target_value is required (hard stop)")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    cfg["source"]["base_url"] = src_url
    cfg["target"]["base_url"] = tgt_url
    return cfg


def main():
    org_key = os.environ["ORG_KEY"]
    config_path = os.environ.get("CONFIG_PATH", f"config/orgs/{org_key}.yml")
    out_path = os.environ.get("CONFIG_OUT", f"/tmp/ts_migration_{org_key}_config.json")

    cfg = load_and_validate(config_path)
    Path(out_path).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Config validated for org '{cfg['org_key']}' -> {out_path}")


if __name__ == "__main__":
    main()
