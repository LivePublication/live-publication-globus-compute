# Globus Compute (LivePublication fork) — Distributed Step Crate Provenance

This branch is a fork of Globus Compute tailored for research on step-level provenance. It adds instrumentation in the worker execution path to emit per-task Distributed Step Crates. These crates can later be assembled into a run-level provenance workflow record.

## Distributed Step Crate Provenance Extension

In this fork, a Distributed Step Crate is a per-task RO-Crate capturing what happened during a single function execution on a worker. The crate is created by the worker process after the task completes and written to disk alongside normal execution artifacts.

What’s captured today:

- Task identity: the crate is positioned/named with the Globus Compute `task_id`.
- Hardware snapshot (at execution time):

  - CPU properties from `lscpu` (model name and related fields).
  - RAM details from `psutil.virtual_memory()`.
  - Storage details parsed from `df` (prototype targets a specific mount).
- Runtime observations during the task:

  - CPU usage time series sampled via `psutil.cpu_percent()` at a fixed poll rate.
  - A PNG plot of CPU usage over the task’s lifetime.
  - Summary statistics (min/max CPU percent) for the observation window.
- Results are assumed to be written to disk within the uses home directory (i.e. where Globus Compute executes tasks).

Notes:

- The crate is not attached to the task’s result payload; it’s persisted locally for later aggregation/collection.
- The crate structure uses RO-Crate entities (e.g., `HardwareComponent`, `Observation`, `HardwareRuntime`) via the `rocrate` library. The crate is created through `lp_sdk.retrospective.crate.DistStepCrate` and then populated with additional entities/files.

## Modified Components in This Branch

This fork introduces the following provenance-specific changes relative to upstream:

- `compute_endpoint/globus_compute_endpoint/engines/helper.py`

  - Function: `execute_task(...)`
  - Adds step-crate generation after user function execution:
    - Starts a CPU monitor before invocation and stops it after completion.
    - Constructs a `DistStepCrate` named `<task_id>.crate`, and calls `add_position(task_id)` to bind task identity.
    - Extracts a hardware snapshot (CPU via `lscpu`, RAM via `psutil`, storage via `df`).
    - Adds RO-Crate entities: `HardwareComponent` (CPU, RAM, Storage), an `Observation` over CPU usage (with JSON timeseries and PNG plot), and a `HardwareRuntime` entity linking the components.
    - Writes the crate to disk via `dist_crate.write()` and cleans up intermediate JSON/PNG files.
- `compute_endpoint/globus_compute_endpoint/engines/simple_hardware.py` (new)

  - Module providing hardware collection and observation utilities used by the worker:
    - `run_hardware_report()` and `parse_hardware_report()` run and parse `lscpu`, `df`, `nvidia-smi`, and Python environment details.
    - `CPUMonitor` class samples `psutil.cpu_percent()` at a configurable interval, writes JSON with timestamps/values, and can output a Matplotlib PNG plot.
    - Helpers for parsing `df` and structuring outputs into dicts suitable for RO-Crate properties.
- `compute_endpoint/setup.py`

  - Packaging changes to enable crate emission:
    - Adds `rocrate` as a dependency.
    - Adds LivePublication’s `lp-sdk` (via VCS URL) to obtain `DistStepCrate`.

## Configuration

Current prototype behavior is always-on in the modified worker path; there is no feature flag in this branch to toggle crate emission.

Relevant parameters and assumptions:

- CPU polling interval: hardcoded to `0.05` seconds in `execute_task()` when starting `CPUMonitor`.
- Crate path: `crate_path = f"{task_id}.crate"` in the worker’s current working directory.
- Storage parsing: the prototype looks for a specific `df` row (e.g., `Mounted == "/mnt/storage"`). This may require adaptation to your environment.

## Usage / Runtime Notes

Submit and execute tasks as you normally would with Globus Compute. When a task completes on the worker:

- A Distributed Step Crate is written locally as `<task_id>.crate`.
- Inside the crate you will find:
  - `data/cpu_usage.json`: time series of CPU percent over the task lifetime.
  - `images/cpu_usage.png`: a plot of the same observation.
  - RO-Crate metadata describing CPU, RAM, and Storage components and an `Observation` about CPU usage, linked under a `HardwareRuntime` entity.
- The task’s result payload is not modified; no crate data is returned to the client by default.

Operational considerations:

- Crate files accumulate where the worker runs. You may want to collect them (e.g., via file transfer) after or during executions for downstream aggregation. This can be done using the [provenance-aware Gladier extension](https://github.com/LivePublication/live-publication-gladier) which manages provenance fragements in the system at runtime.
- The CPU monitor runs concurrently during the task; sampling overhead is expected to be small but non-zero.
