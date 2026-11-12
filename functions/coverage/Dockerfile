FROM fnproject/python:3.11-dev AS build-stage
WORKDIR /function
COPY functions/coverage/requirements.txt .
RUN pip3 install --target /python/ --no-cache-dir -r requirements.txt
COPY src/oci_dashboards /python/oci_dashboards
COPY functions/coverage/func.py /function/func.py
FROM fnproject/python:3.11
WORKDIR /function
COPY --from=build-stage /python /python
COPY --from=build-stage /function/func.py /function/func.py
ENV PYTHONPATH=/function:/python
ENTRYPOINT ["/python/bin/fdk", "/function/func.py", "handler"]
