FROM python:3.10-trixie

WORKDIR /app

COPY . /app/

RUN pip install --no-cache-dir -r requirements.txt

ARG EXTRA_MODULES=""
RUN if [ -n "$EXTRA_MODULES" ]; then \
        pip install --no-cache-dir $EXTRA_MODULES; \
    fi

ENV EVENT_PORT=50060

EXPOSE 50060

CMD ["python3", "-u", "src/main.py"]
