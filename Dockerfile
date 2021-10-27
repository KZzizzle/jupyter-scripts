ARG JUPYTER_MINIMAL_VERSION=dc9744740e12@sha256:0dc8e7bd46d7dbf27c255178ef2d92bb8ca888d32776204d19b5c23f741c1414
FROM jupyter/minimal-notebook:${JUPYTER_MINIMAL_VERSION} as service-base


# TODO: Newest image does not build well jupyterlab extensions
## ARG JUPYTER_MINIMAL_VERSION=54462805efcb@sha256:41c266e7024edd7a9efbae62c4a61527556621366c6eaad170d9c0ff6febc402

LABEL maintainer="KZzizzle" 

ENV JUPYTER_ENABLE_LAB="yes"
ENV NOTEBOOK_TOKEN="simcore"
ENV NOTEBOOK_BASE_DIR="$HOME/work"

USER root

# ffmpeg for matplotlib anim & dvipng for latex labels
RUN apt-get update && \
  apt-get install -y --no-install-recommends ffmpeg dvipng && \
  rm -rf /var/lib/apt/lists/*

RUN pip --no-cache --quiet install --upgrade \
      pip \
      setuptools \
      wheel \
      wget

USER $NB_UID

CMD ["bash"]

# jupyter customizations
RUN conda install --quiet --yes \
    'jupyterlab-git~=0.20.0' \
    && \
    conda clean --all -f -y && \
    # lab extensions
    # https://github.com/jupyter-widgets/ipywidgets/tree/master/packages/jupyterlab-manager
    jupyter labextension install @jupyter-widgets/jupyterlab-manager@^2.0.0 --no-build && \
    # https://github.com/matplotlib/ipympl
    jupyter labextension install jupyter-matplotlib@^0.7.2 --no-build && \
    # https://www.npmjs.com/package/jupyterlab-plotly
    jupyter labextension install jupyterlab-plotly@^4.8.1 --no-build &&\
    # ---
    jupyter lab build -y && \
    jupyter lab clean -y && \
    npm cache clean --force && \
    rm -rf /home/$NB_USER/.cache/yarn && \
    rm -rf /home/$NB_USER/.node-gyp && \
    fix-permissions $CONDA_DIR && \
    fix-permissions /home/$NB_USER


# sidecar functionality -------------------------------------

# set up oSparc env variables
ENV INPUTS_FOLDER="${NOTEBOOK_BASE_DIR}/inputs" \
  OUTPUTS_FOLDER="${NOTEBOOK_BASE_DIR}/outputs" \
  SIMCORE_NODE_UUID="-1" \
  SIMCORE_USER_ID="-1" \
  SIMCORE_NODE_BASEPATH="" \
  SIMCORE_NODE_APP_STATE_PATH="${NOTEBOOK_BASE_DIR}" \
    STORAGE_ENDPOINT="-1" \
    S3_ENDPOINT="-1" \
    S3_ACCESS_KEY="-1" \
    S3_SECRET_KEY="-1" \
    S3_BUCKET_NAME="-1" \
    POSTGRES_ENDPOINT="-1" \
    POSTGRES_USER="-1" \
    POSTGRES_PASSWORD="-1" \
    POSTGRES_DB="-1"

# Copying boot scripts
COPY --chown=$NB_UID:$NB_GID docker /docker

# Copying packages/common
COPY --chown=$NB_UID:$NB_GID packages/jupyter-commons /packages/jupyter-commons
COPY --chown=$NB_UID:$NB_GID packages/jupyter-commons/common_jupyter_notebook_config.py /home/$NB_USER/.jupyter/jupyter_notebook_config.py
COPY --chown=$NB_UID:$NB_GID packages/jupyter-commons/state_puller.py /docker/state_puller.py

# Installing all dependences to run handlers & remove packages
RUN pip install /packages/jupyter-commons
USER root
RUN rm -rf /packages
USER $NB_USER

ENV PYTHONPATH="/src:$PYTHONPATH"
RUN mkdir --parents --verbose "${INPUTS_FOLDER}"; \
  mkdir --parents --verbose "${OUTPUTS_FOLDER}/output_1" \
  mkdir --parents --verbose "${OUTPUTS_FOLDER}/output_2" \
  mkdir --parents --verbose "${OUTPUTS_FOLDER}/output_3" \
  mkdir --parents --verbose "${OUTPUTS_FOLDER}/output_4"

EXPOSE 8888

ENTRYPOINT [ "/bin/bash", "/docker/run.bash" ]

# --------------------------------------------------------------------
FROM service-base as service-with-kernel

# Install kernel in virtual-env
ENV HOME="/home/$NB_USER"

USER root

# Install dependencies for installing FSL, Freesurfer, 
RUN apt-get update && \ 
    apt-get install -yq --no-install-recommends \ 
        zip \
        unzip \
        gnupg2 \
        && \ 
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install FSL
ENV FSLDIR="/usr/share/fsl/5.0"
ENV PATH=${FSLDIR}"/bin:"${PATH}
RUN wget -O- http://neuro.debian.net/lists/bionic.us-nh.full | sudo tee /etc/apt/sources.list.d/neurodebian.sources.list  && \ 
    apt-key adv --recv-keys --keyserver keyserver.ubuntu.com 0xA5D32F012649A5A9 && \ 
    apt-get update && \ 
    apt-get install -y --no-install-recommends fsl-complete && \ 
    apt-get clean && rm -rf /var/lib/apt/lists/* && \ 
    echo . ${FSLDIR}/etc/fslconf/fsl.sh >> ~/.bashrc && \
    echo PATH=${FSLDIR}/bin:${PATH} >> ~/.bashrc && \
    chown -R $NB_USER /usr/share/fsl/

# Install Freesurfer
ENV SUBJECTS_DIR=$NOTEBOOK_BASE_DIR/"subjects"
ENV FREESURFER_HOME="/usr/local/freesurfer"

RUN wget ftp://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/6.0.0/freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.0.tar.gz && \ 
    mv freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.0.tar.gz /usr/local && \ 
    cd /usr/local && \ 
    tar xzvf freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.0.tar.gz && \
    mkdir -p "$SUBJECTS_DIR" && \
    echo source $FREESURFER_HOME/SetUpFreeSurfer.sh >> ~/.bashrc
# License obtained by registering at https://surfer.nmr.mgh.harvard.edu/registration.html
COPY license.txt /usr/local/freesurfer/license.txt

# Install mrtrix 3
RUN apt-get update && \ 
    apt-get install -y --no-install-recommends \
        g++ \
        libgsl0-dev \
        zlib1g-dev \
        mesa-common-dev \
        libglu1-mesa-dev \
        freeglut3-dev \
        libeigen3-dev \
        libqt5charts5 \
        libqt5charts5-dev \
        libqt5widgets5 \
        libqt5gui5 \
        libqt5dbus5 \
        libqt5network5 \
        libqt5core5a \
        qt5-qmake \
        qt5-default \
        libqt5charts5-dev \
        libqt5opengl5-dev \
        libqt5svg5* \
        && \ 
    apt-get clean && rm -rf /var/lib/apt/lists/* && \ 
    git clone https://github.com/jdtournier/mrtrix3.git && \
    cd mrtrix3 && \
    ./configure && \
    ./build && \
    echo "NumberOfThreads: 4" > ~/.mrtrix.conf && \
    echo export PATH=$(pwd)/scripts:$(pwd)/bin:\$PATH >> ~/.bashrc


# Install MNE, must register to get the compressed file: https://www.nmr.mgh.harvard.edu/martinos/userInfo/data/MNE_register/index.php
COPY MNE-2.7.0-3106-Linux-x86_64.tar.gz .
ENV MNE_ROOT=$HOME"/MNE-2.7.0-3106-Linux-x86_64"
RUN tar xzvf MNE-2.7.0-3106-Linux-x86_64.tar.gz && \
    echo source $MNE_ROOT/bin/mne_setup_sh >> ~/.bashrc 

RUN conda install --quiet --yes \
  'texinfo' \
  && \
  conda clean -tipsy && \
  fix-permissions $CONDA_DIR && \
  fix-permissions /home/$NB_USER

USER $NB_UID
WORKDIR ${HOME}

RUN git clone https://github.com/timpx/scripts && \
    python3 -m venv .venv &&\
    .venv/bin/pip --no-cache --quiet install --upgrade \
        pip \
        wheel \
        setuptools \
        &&\
    .venv/bin/pip --no-cache --quiet install \
        ipykernel \
        numpy \
        matplotlib \
        &&\
    .venv/bin/python -m ipykernel install \
        --user \
        --name "python-scripts" \
        --display-name "python SCRIPTS" \
    && \
    jupyter kernelspec list


WORKDIR ${NOTEBOOK_BASE_DIR} 

# COPY --chown=$NB_UID:$NB_GID CHANGELOG.md ${NOTEBOOK_BASE_DIR}/CHANGELOG.md




