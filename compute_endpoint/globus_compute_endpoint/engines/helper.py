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
from .simple_hardware import parse_hardware_report, CPUMonitor
from rocrate.model import ContextEntity, DataEntity
import json

log = logging.getLogger(__name__)

serializer = ComputeSerializer()

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

    env_details = get_env_details()

    # Start example CPU monitoring 
    cpu_observation_pollrate = 0.05
    cpu_monitor = CPUMonitor(interval=cpu_observation_pollrate)
    cpu_monitor.start()

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

    log.warning(
        "task %s completed in %d ns",
        task_id,
        (exec_end.timestamp - exec_start.timestamp),
    )

    # Stop cpu_monitor and return json 
    cpu_monitor.stop()
    cpu_usage_data = cpu_monitor.get_data()
    cpu_usage_fig = cpu_monitor.plot_cpu_usage()

    crate_path = f'{result_message.get("task_id")}.crate'
    dist_crate = DistStepCrate(crate_path)
    dist_crate.add_position(result_message.get("task_id"))
    
    # Temp crate manipulation (will be refactored and moved to lp_sdk)
    hardware = parse_hardware_report()
    temp_crate = dist_crate.crate
    main_entity = temp_crate.mainEntity

    lscpu_shell = hardware["lscpu"]["shell"]
    cpu_component = temp_crate.add(ContextEntity(
        crate=temp_crate,
        properties={
            '@type': 'HardwareComponent',
            'name': 'CPU',
            'description': 'CPU properties as reported by lscpu',
            **{key: value for key, value in lscpu_shell.items()}
        }
    ))

    cpu_observation_fig = temp_crate.add_file(
        cpu_usage_fig,
        dest_path='images/cpu_usage.png',
        properties={
            "name": "CPU usage",
            "encodingFormat": "image/png"
        })

    cpu_observation_data = temp_crate.add_file(
        cpu_usage_data,
        dest_path='data/cpu_usage.json',
        properties={
            "name": "CPU usage",
            "encodingFormat": "json"
        }
    )

    cpu_observation = temp_crate.add(ContextEntity(
        crate=temp_crate,
        properties={
            '@type': 'Observation',
            'observationAbout': cpu_component.id,
            'measurementTechnique': f"Psutil.cpu_percent polled at {cpu_observation_pollrate}",
            'image': cpu_observation_fig.id,
            'maxValue': cpu_monitor.get_max_cpu_usage(),
            'minValue': cpu_monitor.get_min_cpu_usage(),
            'value': cpu_observation_data.id
        }
    ))

    cpu_component.append_to("performance", cpu_observation.id)

    ram_details = hardware["globus_compute_endpoint.engines.simple_hardware.mem_info()"]["python"]
    ram_component = temp_crate.add(ContextEntity(
        crate=temp_crate,
        properties={
            '@type': 'HardwareComponent',
            'name': 'RAM',
            'description': 'RAM properties as reported by mem_info()',
            **{key: value for key, value in ram_details.items()}
        }
    ))

    gen_storage = hardware["df"]["shell"]
    storage_details = next((item for item in gen_storage if item["Mounted"] == "/mnt/storage"), None)
    storage_component = temp_crate.add(ContextEntity(
        crate=temp_crate,
        properties={
            '@type': 'HardwareComponent',
            'name': 'Storage',
            'description': 'Storage properties as reported by ds',
            **{key: value for key, value in storage_details.items()}
        }
    ))

    hardware_runtime = temp_crate.add(ContextEntity(
        crate=temp_crate,
        properties={
            '@type': 'HardwareRuntime',
            'components': {
                lscpu_shell["Model name"]: cpu_component.id,
                'RAM': ram_component.id,
                'DRIVE': storage_component.id
            }
        }
    ))

    main_entity['hasPart'] = hardware_runtime
    dist_crate.write()

    # Clean up env 
    if os.path.exists(cpu_usage_data):
        os.remove(cpu_usage_data)
    if os.path.exists(cpu_usage_fig):
        os.remove(cpu_usage_fig)

    log.warning("CPU data and fig deleted.")
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
