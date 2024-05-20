import platform
import sys
import shlex
import shutil
import subprocess
import json
import os
import logging
import time
import json
import threading
import psutil
import matplotlib.pyplot as plt
from datetime import datetime

log = logging.getLogger(__name__)

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

def mem_info() -> str:
    import psutil  # import here bc psutil is installed with endpoint but not sdk

    svmem = psutil.virtual_memory()
    return "\n".join(f"{k}: {v}" for k, v in svmem._asdict().items())

def python_version() -> str:
    return str(sys.version)

def parse_hardware_report():
    report = run_hardware_report()
    lines = report.strip().split('\n')
    parsed_data = {}
    current_section = None
    current_subsection = None
    current_value = []

    for line in lines:
        if line.startswith('=='):
            if current_section:
                if current_subsection:
                    parsed_data[current_section][current_subsection] = parse_subsection('\n'.join(current_value).strip())
                else:
                    parsed_data[current_section] = parse_subsection('\n'.join(current_value).strip())
                current_value = []

            parts = line.strip('== ').split(': ')
            current_section = parts[1].strip()
            current_subsection = parts[0].strip()
            if current_section not in parsed_data:
                parsed_data[current_section] = {}

        else:
            current_value.append(line)

    if current_section:
        if current_subsection:
            parsed_data[current_section][current_subsection] = parse_subsection('\n'.join(current_value).strip())
        else:
            parsed_data[current_section] = parse_subsection('\n'.join(current_value).strip())

    return parsed_data

def parse_subsection(subsection_data):
    if 'Filesystem' in subsection_data and 'Mounted on' in subsection_data:
        return parse_df_output(subsection_data)
    elif ':' in subsection_data:
        parsed_subsection = {}
        lines = subsection_data.split('\n')
        for line in lines:
            if ': ' in line:
                key, value = line.split(': ', 1)
                parsed_subsection[key.strip()] = value.strip()
            else:
                parsed_subsection[line.strip()] = None
        return parsed_subsection
    else:
        return subsection_data

def parse_df_output(df_data):
    lines = df_data.split('\n')
    headers = lines[0].split()
    filesystems = []
    for line in lines[1:]:
        if line.strip():
            values = line.split()
            filesystem_info = dict(zip(headers, values))
            filesystems.append(filesystem_info)
    return filesystems


class CPUMonitor:
    
    def __init__(self, interval=1):
        self.interval = interval
        self.cpu_usage_data = []
        self.running = False
        self.thread = None

    def _monitor(self):
        while self.running:
            cpu_usage = psutil.cpu_percent(interval=None)
            timestamp = datetime.utcnow().isoformat() + 'Z'  # ISO 8601 format
            self.cpu_usage_data.append({'timestamp': timestamp, 'cpu_percent': cpu_usage})
            time.sleep(self.interval)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._monitor)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def get_data(self, output_file='cpu_usage.json'):
        with open(output_file, 'w') as f:
            json.dump(self.cpu_usage_data, f, indent=2)
        return output_file

    def get_max_cpu_usage(self):
        if not self.cpu_usage_data:
            return None
        return max(self.cpu_usage_data, key=lambda x: x['cpu_percent'])

    def get_min_cpu_usage(self):
        if not self.cpu_usage_data:
            return None
        return min(self.cpu_usage_data, key=lambda x: x['cpu_percent'])

    def plot_cpu_usage(self, output_file='cpu_usage.png'):
        # Convert timestamps to datetime objects
        timestamps = [datetime.fromisoformat(data['timestamp'].replace('Z', '')) for data in self.cpu_usage_data]
        cpu_percentages = [data['cpu_percent'] for data in self.cpu_usage_data]

        # Create the plot
        plt.figure(figsize=(10, 6))
        plt.plot(timestamps, cpu_percentages, marker='o', linestyle='-', color='b')
        plt.title('CPU Usage Over Time')
        plt.xlabel('Time')
        plt.ylabel('CPU Usage (%)')
        plt.grid(True)
        plt.xticks(rotation=45)
        plt.tight_layout()

        # Save the plot as a PNG file
        plt.savefig(output_file)
        plt.close()

        return output_file

def monitor_cpu_usage(interval=1, duration=60):
    monitor = CPUMonitor(interval=interval)
    monitor.start()
    time.sleep(duration)
    monitor.stop()
    return monitor.get_data()