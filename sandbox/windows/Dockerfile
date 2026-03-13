FROM mcr.microsoft.com/windows:ltsc2019

SHELL ["cmd", "/S", "/C"]

RUN mkdir C:\sandbox

WORKDIR C:\sandbox

VOLUME ["C:\\sandbox\\binaries"]

REM Default entrypoint: interactive shell inside the sandbox
CMD ["cmd.exe"]
