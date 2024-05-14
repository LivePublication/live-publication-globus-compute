import logging
import os
import time
import typing as t
import uuid

from globus_compute_common import messagepack
from globus_compute_common.messagepack.message_types import Result, Task, TaskTransition
from globus_compute_common.tasks import ActorName, TaskState
from globus_compute_endpoint.engines.high_throughput.messages import Message
from globus_compute_endpoint.exception_handling import (
    get_error_string,
    get_result_error_details,
)
from globus_compute_endpoint.exceptions import CouldNotExecuteUserTaskError
from globus_compute_sdk.errors import MaxResultSizeExceeded
from globus_compute_sdk.sdk.utils import get_env_details
from globus_compute_sdk.serialize import ComputeSerializer
from parsl.app.python import timeout

# Distributed Step Crate imports
from lp_sdk.retrospective.crate import DistStepCrate
import platform
import sys
import shlex
import shutil
import subprocess

log = logging.getLogger(__name__)

serializer = ComputeSerializer()

def _run_command(cmd: str) -> str | None:
    logger = logging.getLogger(__name__)  # get logger at call site (ie, endpoint)

    cmd_list = shlex.split(cmd)
    arg0 = cmd_list[0]

    if not shutil.which(arg0):
        logger.info(f"{arg0} was not found in the PATH")
        return None

    try:
        res = subprocess.run(cmd_list, timeout=30, capture_output=True, text=True)
        if res.stdout:
            return str(res.stdout)
        if res.stderr:
            return str(res.stderr)
        return "Warning: command had no output on stdout or stderr"
    except subprocess.TimeoutExpired:
        logger.exception(f"Command `{cmd}` timed out")
        return (
            "Error: command timed out (took more than 30 seconds). "
            "See endpoint logs for more details."
        )
    except Exception as e:
        logger.exception(f"Command `{cmd}` failed")
        return (
            f"An error of type {type(e).__name__} occurred. "
            "See endpoint logs for more details."
        )

def mem_info() -> str:
    import psutil  # import here bc psutil is installed with endpoint but not sdk

    svmem = psutil.virtual_memory()
    return "\n".join(f"{k}: {v}" for k, v in svmem._asdict().items())

def python_version() -> str:
    return str(sys.version)

def run_hardware_report() -> str:
    commands = [
        platform.processor,
        os.cpu_count,
        "lscpu",
        "lshw -C display",
        "nvidia-smi",
        mem_info,
        "df",
        platform.node,
        platform.platform,
        python_version,
        "globus-compute-endpoint version",
    ]

    outputs = []
    for cmd in commands:
        if callable(cmd):
            display_name = getattr(
                cmd, "display_name", f"{cmd.__module__}.{cmd.__name__}()"
            )
            display_name = f"python: {display_name}"
            output = cmd()
        else:
            display_name = f"shell: {cmd}"
            output = _run_command(cmd)

        if output:
            outputs.append(f"== {display_name} ==\n{output}")

    return "\n\n".join(outputs)

def execute_task(
    task_id: uuid.UUID,
    task_body: bytes,
    endpoint_id: t.Optional[uuid.UUID],
    result_size_limit: int = 10 * 1024 * 1024,
) -> bytes:
    """Execute task is designed to enable any executor to execute a Task payload
    and return a Result payload, where the payload follows the globus-compute protocols
    This method is placed here to make serialization easy for executor classes
    Parameters
    ----------
    task_id: uuid string
    task_body: packed message as bytes
    endpoint_id: uuid string or None
    result_size_limit: result size in bytes
    Returns
    -------
    messagepack packed Result
    """
    exec_start = TaskTransition(
        timestamp=time.time_ns(), state=TaskState.EXEC_START, actor=ActorName.WORKER
    )

    result_message: dict[
        str,
        uuid.UUID | str | tuple[str, str] | list[TaskTransition] | dict[str, str],
    ]

    log.warning(run_hardware_report())

    env_details = get_env_details()
    try:
        _task, task_buffer = _unpack_messagebody(task_body)
        log.warning("executing task task_id='%s'", task_id)
        result = _call_user_function(task_buffer, result_size_limit=result_size_limit)
        log.warning("Execution completed without exception")
        result_message = dict(task_id=task_id, data=result)

    except Exception:
        log.exception("Caught an exception while executing user function")
        code, user_message = get_result_error_details()
        error_details = {"code": code, "user_message": user_message}
        result_message = dict(
            task_id=task_id,
            data=get_error_string(),
            exception=get_error_string(),
            error_details=error_details,
        )

    env_details["endpoint_id"] = endpoint_id
    result_message["details"] = env_details

    exec_end = TaskTransition(
        timestamp=time.time_ns(),
        state=TaskState.EXEC_END,
        actor=ActorName.WORKER,
    )

    result_message["task_statuses"] = [exec_start, exec_end]
    result_message["TEST"] = "Hello World!"

    log.warning(
        "task %s completed in %d ns",
        task_id,
        (exec_end.timestamp - exec_start.timestamp),
    )

    crate_path = f'{result_message.get("task_id")}.crate'
    log.warning(f"crate_path: {crate_path}")
    dist_crate = DistStepCrate(crate_path)
    dist_crate.add_position(result_message.get("task_id"))
    dist_crate.write()

    log.warning(f"result_message: {result_message}")


    return messagepack.pack(Result(**result_message))


def _unpack_messagebody(message: bytes) -> t.Tuple[Task, str]:
    """Unpack messagebody as a messagepack message with
    some legacy handling
    Parameters
    ----------
    message: messagepack'ed message body
    Returns
    -------
    tuple(task, task_buffer)
    """
    try:
        task = messagepack.unpack(message)
        if not isinstance(task, messagepack.message_types.Task):
            raise CouldNotExecuteUserTaskError(
                f"wrong type of message in worker: {type(task)}"
            )
        task_buffer = task.task_buffer
    # on parse errors, failover to trying the "legacy" message reading
    except (
        messagepack.InvalidMessageError,
        messagepack.UnrecognizedProtocolVersion,
    ):
        task = Message.unpack(message)
        assert isinstance(task, Task)
        task_buffer = task.task_buffer.decode("utf-8")  # type: ignore[attr-defined]
    return task, task_buffer


def _call_user_function(
    task_buffer: str, result_size_limit: int, serializer=serializer
) -> str:
    """Deserialize the buffer and execute the task.
    Parameters
    ----------
    task_buffer: serialized buffer of (fn, args, kwargs)
    result_size_limit: size limit in bytes for results
    serializer: serializer for the buffers
    Returns
    -------
    Returns serialized result or throws exception.
    """
    GC_TASK_TIMEOUT = max(0.0, float(os.environ.get("GC_TASK_TIMEOUT", 0.0)))
    f, args, kwargs = serializer.unpack_and_deserialize(task_buffer)
    if GC_TASK_TIMEOUT > 0.0:
        log.debug(f"Setting task timeout to GC_TASK_TIMEOUT={GC_TASK_TIMEOUT}s")
        f = timeout(f, GC_TASK_TIMEOUT)

    result_data = f(*args, **kwargs)
    serialized_data = serializer.serialize(result_data)

    if len(serialized_data) > result_size_limit:
        raise MaxResultSizeExceeded(len(serialized_data), result_size_limit)

    return serialized_data
