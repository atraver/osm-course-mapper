FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
RUN pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: \
    numpy==2.2.6 onnxruntime==1.23.2 opencv-python-headless==4.12.0.88 shapely==2.1.2
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2
WORKDIR /tool
COPY *.py ./
COPY viewer ./viewer
USER 10001:10001
ENTRYPOINT ["python", "/tool/propose.py"]
