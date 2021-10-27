import logging
import os
import tempfile
import shutil
from pathlib import Path
from contextlib import contextmanager

from notebook.base.handlers import IPythonHandler
from notebook.utils import url_path_join

from simcore_sdk.node_ports_v2 import exceptions
from simcore_sdk.node_data import data_manager

from servicelib.archiving_utils import archive_dir

log = logging.getLogger(__name__)

_STATE_PATH = os.environ.get("SIMCORE_NODE_APP_STATE_PATH", "undefined") # typically /home/jovian/work


@contextmanager
def get_temp_name(path_to_compress: Path) -> Path:
    base_dir = Path(tempfile.mkdtemp())
    zip_temp_name = base_dir / f"{path_to_compress.name}.zip"
    try:
        yield zip_temp_name
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def _state_path() -> Path:
    assert _STATE_PATH != "undefined", "SIMCORE_NODE_APP_STATE_PATH is not defined!"
    state_path = Path(_STATE_PATH)
    return state_path


class StateHandler(IPythonHandler):
    def initialize(self):  # pylint: disable=no-self-use
        pass

    async def post(self):
        log.info("started pushing current state to S3...")
        try:
            path_to_archive = _state_path()
            with get_temp_name(path_to_archive) as archive_path:
                succeeded = await archive_dir(
                    dir_to_compress=path_to_archive,
                    destination=archive_path,
                    compress=False,
                    store_relative_path=True,
                )
                if not succeeded:
                    raise ValueError("There was an error while archiving")

                await data_manager.push(archive_path)

            self.set_status(204)
        except (exceptions.NodeportsException, ValueError) as exc:
            log.exception("Unexpected error while pushing state")
            self.set_status(500, reason=str(exc))
        finally:
            self.finish()

    async def get(self):
        log.info("started pulling state to S3...")
        try:
            await data_manager.pull(_state_path())
            self.set_status(204)
        except exceptions.S3InvalidPathError as exc:
            log.exception("Invalid path to S3 while retrieving state")
            self.set_status(404, reason=str(exc))
        except exceptions.NodeportsException as exc:
            log.exception("Unexpected error while retrieving state")
            self.set_status(500, reason=str(exc))
        finally:
            self.finish("completed pulling state")


def load_jupyter_server_extension(nb_server_app):
    """Called when the extension is loaded

    - Adds API to server

    :param nb_server_app: handle to the Notebook webserver instance.
    :type nb_server_app: NotebookWebApplication
    """
    web_app = nb_server_app.web_app
    host_pattern = ".*$"
    route_pattern = url_path_join(web_app.settings["base_url"], "/state")

    web_app.add_handlers(host_pattern, [(route_pattern, StateHandler)])
