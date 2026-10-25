FROM python:3.13-slim
RUN pip install --no-cache-dir pandas==2.3.3 openpyxl==3.1.5 xlsxwriter==3.2.9 matplotlib==3.10.7
USER 65534:65534
WORKDIR /work
CMD ["python", "-I"]
