import logging

from rocrate.rocrate import ROCrate
from rocrate.rocrate import ContextEntity, DataEntity

from globus_compute_sdk.serialize import ComputeSerializer

log = logging.getLogger(__name__)

compute_serializer = ComputeSerializer()

def generate_step_crate(result_message, _task, task_buffer):
  function, args, kwargs = compute_serializer.unpack_and_deserialize(task_buffer)

  for field, value in result_message.items():
    log.warning(f"{field}: {value}")
  
  crate = ROCrate()
  log.warning("Building Distriubted Step Crate")

  # --------------- Dist step -----------------
  distriubted_step = crate.add(DataEntity(
      crate=crate,
      identifier="distriubted_step",
      properties={
          "@type": ["CreateAction", 
                    "HowTo", 
                    "ActionAccessSpecification",
                    "Schedule"],
      }
  ))
  crate.mainEntity = distriubted_step

  # --------------- HowToStep -----------------
  postion = crate.add(ContextEntity(
        crate=crate,
        properties={
            "@type": "HowToStep",
            "position": result_message['task_id']
        }
    ))
  distriubted_step['step'] = postion

  # --------------- write crate ----------------
  crate.write(f"{result_message['task_id']}.crate")


"""

 # Build Distriubted Step Crate

    log.warning("Building Distriubted Step Crate")
    crate = ROCrate()
    distriubted_step = crate.add(DataEntity(
        crate=crate,
        identifier="distriubted_step",
        properties={
            "@type": ["CreateAction", 
                      "HowTo", 
                      "ActionAccessSpecification",
                      "Schedule"],
        }
    ))
    crate.mainEntity = distriubted_step

    postion = crate.add(ContextEntity(
        crate=crate,
        properties={
            "@type": "HowToStep",
            "position": task_id
        }
    ))
    distriubted_step['step'] = postion

    crate.write(f"{task_id}.crate")
    # crate.write_zip(f"{task_id}.crate")

    f, args, kwargs = serializer.unpack_and_deserialize(task_buffer)
    log.warning(f"Function: {inspect.getsource(f)}") 
    log.warning(f"Args: {args}")
    log.warning(f"Kwargs: {kwargs}")

"""