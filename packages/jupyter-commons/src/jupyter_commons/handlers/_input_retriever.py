import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import zipfile
from functools import wraps
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from simcore_sdk import node_ports_v2
from simcore_sdk.node_ports_v2 import Nodeports, Port
# NOTE: ItemConcreteValue = Union[int, float, bool, str, Path]
from simcore_sdk.node_ports_v2.links import ItemConcreteValue

from servicelib.archiving_utils import archive_dir, unarchive_dir, PrunableFolder

logger = logging.getLogger(__name__)

_INPUTS_FOLDER = os.environ.get("INPUTS_FOLDER")
_OUTPUTS_FOLDER = os.environ.get("OUTPUTS_FOLDER")
_FILE_TYPE_PREFIX = "data:"
_KEY_VALUE_FILE_NAME = "key_values.json"


def run_sequentially(loop=None):
    """Multiple calls to decorated function will run sequentially """

    def internal(decorated_function):
        _loop = asyncio.get_event_loop() if loop is None else loop

        in_queue = asyncio.Queue()
        out_queue = asyncio.Queue()
        initialized = False

        @wraps(decorated_function)
        async def wrapper(*args, **kwargs):
            nonlocal initialized
            if not initialized:
                initialized = True
                # todo run worker here for the queues in different thread

                async def worker(in_q: asyncio.Queue, out_q: asyncio.Queue):
                    while True:
                        awaitable = await in_q.get()
                        in_q.task_done()
                        await out_q.put(await awaitable)

                _loop.create_task(worker(in_queue, out_queue))

            await in_queue.put(decorated_function(*args, **kwargs))

            return await out_queue.get()

        return wrapper

    return internal


async def get_data_from_port(port: Port) -> Tuple[Port, ItemConcreteValue]:
    logger.info("transfer started for %s", port.key)
    start_time = time.perf_counter()
    ret = await port.get()
    elapsed_time = time.perf_counter() - start_time
    logger.info("transfer completed in %ss", elapsed_time)
    if isinstance(ret, Path):
        size_mb = ret.stat().st_size / 1024 / 1024
        logger.info(
            "%s: data size: %sMB, transfer rate %sMB/s",
            ret.name,
            size_mb,
            size_mb / elapsed_time,
        )
    return (port, ret)


async def set_data_to_port(port: Port, value: Optional[Any]):
    logger.info("transfer started for %s", port.key)
    start_time = time.perf_counter()
    await port.set(value)
    elapsed_time = time.perf_counter() - start_time
    logger.info("transfer completed in %ss", elapsed_time)
    if isinstance(value, Path):
        size_bytes = value.stat().st_size
        logger.info(
            "%s: data size: %sMB, transfer rate %sMB/s",
            value.name,
            size_bytes / 1024 / 1024,
            size_bytes / 1024 / 1024 / elapsed_time,
        )
        return size_bytes
    return sys.getsizeof(value)


async def download_data(port_keys: List[str]) -> int:
    logger.info("retrieving data from simcore...")
    start_time = time.perf_counter()
    PORTS: Nodeports = await node_ports_v2.ports()
    inputs_path = Path(_INPUTS_FOLDER).expanduser()
    data = {}

    # let's gather all the data
    download_tasks = []
    for node_input in (await PORTS.inputs).values():
        # if port_keys contains some keys only download them
        logger.info("Checking node %s", node_input.key)
        if port_keys and node_input.key not in port_keys:
            continue
        # collect coroutines
        download_tasks.append(get_data_from_port(node_input))
    logger.info("retrieving %s data", len(download_tasks))

    transfer_bytes = 0
    if download_tasks:
        # TODO: limit concurrency to avoid saturating storage+db??
        results: List[Tuple[Port, ItemConcreteValue]] = await asyncio.gather(*download_tasks)
        logger.info("completed download %s", results)
        for port, value in results:

            data[port.key] = {"key": port.key, "value": value}

            if _FILE_TYPE_PREFIX in port.property_type:

                # if there are files, move them to the final destination
                downloaded_file: Optional[Path] = value
                dest_path: Path = inputs_path / port.key

                if not downloaded_file or not downloaded_file.exists():
                    # the link may be empty
                    continue

                transfer_bytes = transfer_bytes + downloaded_file.stat().st_size

                # in case of valid file, it is either uncompressed and/or moved to the final directory
                logger.info("creating directory %s", dest_path)
                dest_path.mkdir(exist_ok=True, parents=True)
                data[port.key] = {"key": port.key, "value": str(dest_path)}

                if zipfile.is_zipfile(downloaded_file):

                    dest_folder = PrunableFolder(dest_path)

                    # unzip updated data to dest_path
                    logger.info("unzipping %s", downloaded_file)
                    unarchived: Set[Path] = await unarchive_dir(
                        archive_to_extract=downloaded_file, destination_folder=dest_path
                    )

                    dest_folder.prune(exclude=unarchived)

                    logger.info("all unzipped in %s", dest_path)
                else:
                    logger.info("moving %s", downloaded_file)
                    dest_path = dest_path / Path(downloaded_file).name
                    shutil.move(downloaded_file, dest_path)
                    logger.info("all moved to %s", dest_path)
            else:
                transfer_bytes = transfer_bytes + sys.getsizeof(value)

    # create/update the json file with the new values
    if data:
        data_file = inputs_path / _KEY_VALUE_FILE_NAME
        if data_file.exists():
            current_data = json.loads(data_file.read_text())
            # merge data
            data = {**current_data, **data}
        data_file.write_text(json.dumps(data))
    stop_time = time.perf_counter()
    logger.info(
        "all data retrieved from simcore in %s seconds: %s",
        stop_time - start_time,
        data,
    )
    return transfer_bytes


@run_sequentially()
async def upload_data(port_keys: List[str]) -> int:
    """calls to this function will get queued and invoked in sequence"""
    # pylint: disable=too-many-branches
    logger.info("uploading data to simcore...")
    start_time = time.perf_counter()
    PORTS: Nodeports = await node_ports_v2.ports()
    outputs_path = Path(_OUTPUTS_FOLDER).expanduser()

    # let's gather the tasks
    temp_files: List[Path] = []
    upload_tasks = []
    transfer_bytes = 0
    for port in (await PORTS.outputs).values():
        logger.info("Checking port %s", port.key)
        if port_keys and port.key not in port_keys:
            continue
        logger.debug(
            "uploading data to port '%s' with value '%s'...", port.key, port.value
        )
        if _FILE_TYPE_PREFIX in port.property_type:
            src_folder = outputs_path / port.key
            files_and_folders_list = list(src_folder.rglob("*"))

            if not files_and_folders_list:
                upload_tasks.append(set_data_to_port(port, None))
                continue

            if len(files_and_folders_list) == 1 and files_and_folders_list[0].is_file():
                # special case, direct upload
                upload_tasks.append(set_data_to_port(
                    port, files_and_folders_list[0]))
                continue

            # generic case let's create an archive
            # only the filtered out files will be zipped
            tmp_file = Path(tempfile.mkdtemp()) / f"{src_folder.stem}.zip"
            temp_files.append(tmp_file)

            zip_was_created = await archive_dir(
                dir_to_compress=src_folder,
                destination=tmp_file,
                compress=False,
                store_relative_path=True,
            )
            if zip_was_created:
                upload_tasks.append(set_data_to_port(port, tmp_file))
            else:
                logger.error(
                    "Could not create zip archive, nothing will be uploaded")
        else:
            data_file = outputs_path / _KEY_VALUE_FILE_NAME
            if data_file.exists():
                data = json.loads(data_file.read_text())
                if port.key in data and data[port.key] is not None:
                    upload_tasks.append(set_data_to_port(port, data[port.key]))

    if upload_tasks:
        try:
            results = await asyncio.gather(*upload_tasks)
            transfer_bytes = sum(results)
        finally:
            # clean up possible compressed files
            for file_path in temp_files:
                shutil.rmtree(file_path.parent, ignore_errors=True)

    stop_time = time.perf_counter()
    logger.info("all data uploaded to simcore in %sseconds",
                stop_time - start_time)
    return transfer_bytes
