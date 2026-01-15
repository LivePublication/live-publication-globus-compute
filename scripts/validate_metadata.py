#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PyYAML is required to parse CITATION.cff. Install with: python -m pip install pyyaml"
        ) from exc

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_zenodo(path: Path) -> None:
    data = load_json(path)
    creators = data.get("creators", [])
    require(data.get("title"), "Zenodo: missing title")
    require(data.get("description"), "Zenodo: missing description")
    require(data.get("version") == "1.0.1", "Zenodo: version must be 1.0.1")
    require(data.get("license") == "apache-2.0", "Zenodo: license must be apache-2.0")
    require(creators, "Zenodo: creators missing")
    orcid = creators[0].get("orcid", "")
    require(orcid and "://" not in orcid, "Zenodo: ORCID must be bare (no URL)")


def validate_codemeta(path: Path) -> None:
    data = load_json(path)
    require(data.get("version") == "1.0.1", "CodeMeta: version must be 1.0.1")


def validate_citation(path: Path) -> None:
    data = load_yaml(path)
    require(data.get("version") == "1.0.1", "CITATION.cff: version must be 1.0.1")


def validate_rocrate(path: Path, repo_root: Path) -> None:
    data = load_json(path)
    graph = data.get("@graph", [])
    ids = [entry.get("@id") for entry in graph if "@id" in entry]
    require(len(ids) == len(set(ids)), "RO-Crate: duplicate @id values detected")

    root_dataset = None
    for entry in graph:
        if entry.get("@id") in {"./", ""} and "Dataset" in entry.get("@type", []):
            root_dataset = entry
            break
    if root_dataset is None:
        for entry in graph:
            if entry.get("@id") in {"./", ""}:
                root_dataset = entry
                break

    require(root_dataset is not None, "RO-Crate: root dataset not found")
    has_part = root_dataset.get("hasPart", [])
    for item in has_part:
        rel_id = item.get("@id") if isinstance(item, dict) else item
        if rel_id is None:
            continue
        if rel_id.startswith(("http://", "https://", "doi:", "#")):
            continue
        require(
            not Path(rel_id).is_absolute(),
            f"RO-Crate: hasPart @id must be relative: {rel_id}",
        )
        target = repo_root / rel_id
        require(target.exists(), f"RO-Crate: hasPart path missing: {rel_id}")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    validate_zenodo(repo_root / ".zenodo.json")
    validate_codemeta(repo_root / "codemeta.json")
    validate_citation(repo_root / "CITATION.cff")
    validate_rocrate(repo_root / "ro-crate-metadata.json", repo_root)

    print("Metadata validation passed.")
    print("")
    print("Maintainer checklist:")
    print("- Confirm quickstart steps work on a real Globus endpoint")
    print("- Confirm the Apache-2.0 license matches your intent")
    print("- Confirm Zenodo GitHub integration is enabled for this repository")
    print("- Create a GitHub release/tag v1.0.1")
    print("- Verify the Zenodo DOI is minted after release")
    print("- Patch a 1.0.2 release to add the DOI back into metadata files")


if __name__ == "__main__":
    main()
