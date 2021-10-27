import asyncio
import logging
import os
import time
from functools import wraps
from os.path import expanduser
from pathlib import Path

from tornado.ioloop import IOLoop
from watchdog.events import FileSystemEventHandler, PatternMatchingEventHandler
from watchdog.observers import Observer

from . import _input_retriever

log = logging.getLogger(__name__)

OUTPUTS_FOLDER = Path(os.environ.get("OUTPUTS_FOLDER", "/this_/does/not/exist"))
HOME_FOLDER = expanduser("~")
STATE_PATH = os.environ.get(
    "SIMCORE_NODE_APP_STATE_PATH", "undefined"
)  # typically /home/jovian/work


class AsyncLockedFloat:
    __slots__ = ("_lock", "_value")

    def __init__(self, initial_value=None):
        self._lock = asyncio.Lock()
        self._value = initial_value

    async def set_value(self, value):
        async with self._lock:
            self._value = value

    async def get_value(self):
        async with self._lock:
            return self._value


def async_run_once_after_event_chain(detection_interval):
    """
    The function's call is delayed by a period equal to the
    `detection_interval` and multiple calls during this
    interval will be ignored and will reset the delay.

    param: detection_interval the amount of time between
    returns: decorator to be applied to async functions
    """

    def internal(decorated_function):
        last = AsyncLockedFloat(initial_value=None)

        @wraps(decorated_function)
        async def wrapper(*args, **kwargs):

            # skipping  the first time the event chain starts
            if await last.get_value() is None:
                await last.set_value(time.time())
                return

            await last.set_value(time.time())

            last_read = await last.get_value()
            await asyncio.sleep(detection_interval)

            if last_read == await last.get_value():
                return await decorated_function(*args, **kwargs)

        return wrapper

    return internal


async def push_mapped_data_to_ports():
    transferred_bytes = await _input_retriever.upload_data(port_keys=[])
    log.info("transferred %s bytes", transferred_bytes)


@async_run_once_after_event_chain(detection_interval=1.0)
async def invoke_push_mapped_data():
    await push_mapped_data_to_ports()


def trigger_async_invoke_push_mapped_data(loop: IOLoop):
    loop.spawn_callback(invoke_push_mapped_data)


class UnifyingEventHandler(FileSystemEventHandler):
    def __init__(self, loop: IOLoop):
        super().__init__()

        self.loop: IOLoop = loop

    def on_moved(self, event):
        super().on_moved(event)
        trigger_async_invoke_push_mapped_data(self.loop)

    def on_created(self, event):
        super().on_created(event)
        trigger_async_invoke_push_mapped_data(self.loop)

    def on_deleted(self, event):
        super().on_deleted(event)
        trigger_async_invoke_push_mapped_data(self.loop)

    def on_modified(self, event):
        super().on_modified(event)
        trigger_async_invoke_push_mapped_data(self.loop)


class WorkFolderEventHandler(PatternMatchingEventHandler):
    def __init__(self, wdir: Path):
        assert wdir.is_dir()
        assert wdir.exists()
        self.workdir = wdir.resolve()

        super().__init__(
            patterns=[
                str(self.workdir.name),
            ],
            case_sensitive=True,
            ignore_directories=False,
        )

    def on_deleted(self, event):
        super().on_deleted(event)
        log.error(
            "Unexpected deletion of  %s: ls=\n %s",
            event.src_path,
            list(self.workdir.parent.glob("*")),
        )

        # WARNING: DO NOT restore workdir to avoid overriding copy in S3.
        # NOTE: Keep here just for testing purposes
        # if not self.workdir.exists() and Path(event.src_path) == self.workdir:
        #    log.warning("Restoring %s", self.workdir)
        #    self.workdir.mkdir(parents=True, exist_ok=True)


def start_watcher(tornado_loop: IOLoop):
    # used for run
    if not OUTPUTS_FOLDER.exists():
        log.error(
            "\n\n>>>>>>>>>> ERROR <<<<<<<<<<\nOutputs folder '%s'"
            " does not exist!\nQuitting application!\n\n",
            OUTPUTS_FOLDER,
        )
        tornado_loop.stop()

    observers = []

    log.info("Monitoring %s", str(OUTPUTS_FOLDER))
    outputs_event_handle = UnifyingEventHandler(loop=tornado_loop)
    observer1 = Observer()
    observer1.schedule(outputs_event_handle, str(OUTPUTS_FOLDER), recursive=True)
    observers.append(observer1)

    if os.path.exists(STATE_PATH) and os.path.isdir(STATE_PATH):
        # Restores workdir if deleted to avoid Not Found problem
        workdir = Path(STATE_PATH).resolve()
        log.info("Monitoring %s", workdir)
        log_event_handler = WorkFolderEventHandler(workdir)

        observer2 = Observer()
        observer2.schedule(log_event_handler, str(workdir.parent), recursive=False)
        observers.append(observer2)

    try:
        for observer in observers:
            observer.start()

        while True:
            time.sleep(0.5)

    except Exception:  # pylint: disable=broad-except
        log.exception("Watchers failed upon initialization")
    finally:
        for observer in observers:
            observer.stop()
            observer.join()


def load_jupyter_server_extension(_):
    """Called when the extension is loaded

    - Adds API to server

    :param nb_server_app: handle to the Notebook webserver instance.
    :type nb_server_app: NotebookWebApplication
    """
    # TODO: apt-get install zip in all notebooks if this works and migrate the solution to all of them

    current_loop = IOLoop.current()
    current_loop.run_in_executor(None, start_watcher, current_loop)
