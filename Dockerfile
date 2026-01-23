FROM alphine:latest
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT [ "entrypoint.sh" ]