FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pandas==2.3.3 openpyxl==3.1.5 xlsxwriter==3.2.9 matplotlib==3.10.7
COPY --chmod=644 matplotlibrc /opt/matplotlibrc
ENV MATPLOTLIBRC=/opt/matplotlibrc
USER 65534:65534
WORKDIR /work
CMD ["python", "-I"]
