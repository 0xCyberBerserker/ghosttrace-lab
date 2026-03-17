FROM dockurr/windows:latest

COPY sandbox/windows/entrypoint.sh /usr/local/bin/ghosttrace-windows-entrypoint.sh
RUN chmod +x /usr/local/bin/ghosttrace-windows-entrypoint.sh

ENTRYPOINT ["/usr/bin/tini", "-s", "/usr/local/bin/ghosttrace-windows-entrypoint.sh"]
