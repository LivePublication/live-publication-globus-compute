#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path

from rocrate.rocrate import ROCrate


def add_path(crate: ROCrate, root: Path, added_paths: set[str], rel_path: str) -> None:
    if rel_path in added_paths:
        return

    target = root / rel_path
    if not target.exists():
        raise FileNotFoundError(f"Missing path for RO-Crate: {rel_path}")

    if target.is_dir():
        entity = crate.add_directory(rel_path)
    else:
        entity = crate.add_file(rel_path)

    crate.root_dataset.append_to("hasPart", entity)
    added_paths.add(rel_path)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    crate = ROCrate()

    title = "live-publication-globus-compute (Thesis Artifact)"
    description = (
        "A LivePublication fork of Globus Compute that emits Distributed Step Crate (DSC) "
        "RO-Crate provenance records for each task executed on an endpoint, enabling "
        "step-level provenance packaging in a distributed execution environment."
    )

    crate.root_dataset["name"] = title
    crate.root_dataset["description"] = description
    crate.root_dataset["license"] = "Apache-2.0"
    crate.root_dataset["datePublished"] = date.today().isoformat()
    crate.root_dataset["version"] = "1.0.1"
    crate.root_dataset["identifier"] = "https://doi.org/10.5281/zenodo.18254882"

    software = crate.add_jsonld(
        {
            "@id": "#software",
            "@type": "SoftwareSourceCode",
            "name": title,
            "description": description,
            "version": "1.0.1",
            "license": "Apache-2.0",
            "identifier": "https://doi.org/10.5281/zenodo.18254882",
            "codeRepository": "https://github.com/LivePublication/live-publication-globus-compute",
            "programmingLanguage": "Python",
            "author": [
                {
                    "@id": "https://orcid.org/0000-0001-8260-231X",
                    "@type": "Person",
                    "name": "Augustus Ellerm",
                }
            ],
        }
    )
    crate.root_dataset["mainEntity"] = software

    added_paths: set[str] = set()
    include_paths = [
        "README.md",
        "README.rst",
        "LICENSE",
        ".zenodo.json",
        "codemeta.json",
        "CITATION.cff",
        "CONTRIBUTING.md",
        "RELEASING.md",
        "compute_endpoint",
        "compute_sdk",
        "docs",
        "local_dev",
        "smoke_tests",
        "scripts",
    ]

    for rel_path in include_paths:
        add_path(crate, repo_root, added_paths, rel_path)

    try:
        crate.write(repo_root, generate_preview=False)
    except TypeError:
        crate.write(repo_root)


if __name__ == "__main__":
    main()
