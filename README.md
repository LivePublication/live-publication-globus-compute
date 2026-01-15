# live-publication-globus-compute

## What this repository does

This repository is a LivePublication fork of Globus Compute that extends the worker execution logic to emit a per-task Distributed Step Crate (DSC). Each DSC is an RO-Crate produced after task completion and persisted locally on the worker for later aggregation into a run-level provenance record.

Related works:
- LivePublication interface schemas (Zenodo DOI): https://doi.org/10.5281/zenodo.18250033
- Interactive Distributed Provenance Example (viewer + data) (Zenodo DOI): https://doi.org/10.5281/zenodo.18253488

## Repository structure

- `compute_endpoint/`: Globus Compute endpoint code with DSC emission in the worker execution path.
- `compute_sdk/`: Globus Compute SDK (client-side) code.
- `docs/`: Upstream Globus Compute documentation, including quickstart and endpoint setup.
- `smoke_tests/`: Smoke tests for basic endpoint behavior.
- `local_dev/`: Local development docker-compose scaffolding.

## Inputs

- Globus Compute task execution context (task ID, working directory).
- Hardware and runtime observations gathered on the worker:
  - CPU details from `lscpu`
  - RAM details from `psutil.virtual_memory()`
  - Storage details from `df` (prototype targets a specific mount)
  - CPU usage time series from `psutil.cpu_percent()` sampling
- Environment assumptions:
  - Tasks run on a Linux endpoint with access to the above tools and libraries.

## Outputs

- A Distributed Step Crate written locally as `<task_id>.crate` on the worker.
- Inside the crate:
  - `data/cpu_usage.json` (CPU usage time series)
  - `images/cpu_usage.png` (plot of the same observation)
  - RO-Crate metadata entities describing CPU, RAM, Storage, and a `HardwareRuntime` observation
- The task’s result payload is unchanged; provenance is not returned via the client by default.

## Quickstart

Use the upstream Globus Compute quickstart for installing and running endpoints and the SDK: `docs/quickstart.rst`.

## Reproducibility notes

- DSC emission is always-on in the modified worker path (no feature flag in this branch).
- CPU polling interval is hardcoded to `0.05` seconds in the worker execution path.
- The crate is created via `lp_sdk.retrospective.crate.DistStepCrate` and the `rocrate` library.
- Crate files accumulate in the worker’s current working directory and must be collected separately.
- The endpoint component targets Linux; the SDK can run on macOS, Linux, and Windows (per upstream docs).

## How to cite

- GitHub: https://github.com/LivePublication/live-publication-globus-compute
- Zenodo DOI: https://doi.org/10.5281/zenodo.18254882

## License

Apache-2.0
