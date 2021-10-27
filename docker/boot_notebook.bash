#!/bin/bash
# SEE http://redsymbol.net/articles/unofficial-bash-strict-mode/

set -euo pipefail
IFS=$'\n\t'
INFO="INFO: [$(basename "$0")] "
WARNING="WARNING: [$(basename "$0")] "

# create output folder
echo
echo "$INFO" "creating inputs/outputs folder"
mkdir --parents "${INPUTS_FOLDER}"
mkdir --parents "${OUTPUTS_FOLDER}"

# Restore previous state pulling it from S3
if [ -n "${SIMCORE_NODE_BASEPATH}" ]; then
  echo "$INFO" "Restoring previous state..."
  python /docker/state_puller.py "${SIMCORE_NODE_APP_STATE_PATH}"
else
  echo "$WARNING" "SIMCORE_NODE_APP_STATE_PATH was not set. Saving states feature is disabled."
fi

# Trust all notebooks in the notebooks folder
echo "$INFO" "trust all notebooks in path..."
find "${SIMCORE_NODE_APP_STATE_PATH}" -name '*.ipynb' -type f -exec jupyter trust {} +



# Configure
# Prevents notebook to open in separate tab
mkdir --parents "$HOME/.jupyter/custom"
cat > "$HOME/.jupyter/custom/custom.js" <<EOF
define(['base/js/namespace'], function(Jupyter){
    Jupyter._target = '_self';
});
EOF

#https://github.com/jupyter/notebook/issues/3130 for delete_to_trash
#https://github.com/nteract/hydrogen/issues/922 for disable_xsrf
cat > .jupyter_config.json <<EOF
{
    "NotebookApp": {
        "ip": "0.0.0.0",
        "port": 8888,
        "base_url": "${SIMCORE_NODE_BASEPATH}",
        "extra_static_paths": ["${SIMCORE_NODE_BASEPATH}/static"],
        "notebook_dir": "${SIMCORE_NODE_APP_STATE_PATH}",
        "token": "",
        "quit_button": false,
        "open_browser": false,
        "webbrowser_open_new": 0,
        "disable_check_xsrf": true,
        "nbserver_extensions": {
            "jupyter_commons.handlers.retrieve": true,
            "jupyter_commons.handlers.push": true,
            "jupyter_commons.handlers.state": true,
            "jupyter_commons.handlers.watcher": true
        }
    },
    "FileCheckpoints": {
        "checkpoint_dir": "/home/jovyan/._ipynb_checkpoints/"
    },
    "KernelSpecManager": {
        "ensure_native_kernel": false
    },
    "Session": {
        "debug": false
    },
    "VoilaConfiguration" : {
        "enable_nbextensions" : true
    }
}
EOF

# shellcheck disable=SC1091
source .venv/bin/activate

#   TODO: This should only be a temporary solution until the dynamic sidecar is unleashed
#
#   There are two flavors of this service jsmash and jsmash-voila. They are identical except
#   that the voila version has an environment variable AS_VOILA=1 (set via labels).
#   So if the user starts the voila one, we keep the preview extension so that she can edit
#   her work in the lab. However, if there is a file voila.ipynb in the work folder, we
#   switch to voila mode. read-only (and default theme?)
#
#   Note: In the pure voila mode, there are not handlers for retrieve/push/state/watcher,
#         but, the state pulling works. Which is the only thing we care about here.
#
#   In the future, we should have a option in the dashboard to configure how jsmash should be
#   initiated (only for the owner of the coresponding study)
#
VOILA_NOTEBOOK="${SIMCORE_NODE_APP_STATE_PATH}"/voila.ipynb

if [ "${AS_VOILA-0}" -ne 1 ]; then
    # disable the preview if this is not the voila service
    jupyter labextension disable  @jupyter-voila/jupyterlab-preview
else
    echo "$INFO" "Found AS_VOILA=${AS_VOILA}... Starting in voila mode"
fi

if [ "${AS_VOILA-0}" -eq 1 ] && [ -f "${VOILA_NOTEBOOK}" ]; then
    echo "$INFO" "Found ${VOILA_NOTEBOOK}... Starting in voila mode"
    voila "${VOILA_NOTEBOOK}" --enable_nbextensions=True --port 8888 --no-browser --base_url=${SIMCORE_NODE_BASEPATH}/
else
    # call the notebook with the basic parameters
    start-notebook.sh --config .jupyter_config.json "$@"
fi
