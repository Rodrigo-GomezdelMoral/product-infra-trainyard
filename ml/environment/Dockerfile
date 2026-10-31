FROM mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:20261018.v1
COPY conda.yaml /tmp/conda.yaml
RUN conda env create -p /azureml-envs/trainyard -f /tmp/conda.yaml && conda clean -aqy && rm -rf /root/.cache/pip
ENV AZUREML_CONDA_ENVIRONMENT_PATH=/azureml-envs/trainyard PATH=/azureml-envs/trainyard/bin:$PATH
