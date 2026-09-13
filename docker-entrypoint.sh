#!/bin/sh
# Process-mode dispatcher for the KnowHub backend image.
#
# One image, several process modes (blueprint §30.1). At M00 only `api` has an
# implementation; `worker` and `scheduler` arrive with the M2 code that backs
# them. There is deliberately no branch for them here, and no shell or debug
# mode: an unknown argument must not fall through to arbitrary execution.

set -eu

mode="${1:-}"

case "${mode}" in
    api)
        shift
        # exec so uvicorn becomes PID 1 and receives SIGTERM directly, which is
        # what makes graceful shutdown (and the readiness drain) work.
        exec uvicorn knowhub.api.main:app --host 0.0.0.0 --port 8000 "$@"
        ;;
    "")
        echo "no process mode given; supported modes: api" >&2
        exit 64
        ;;
    *)
        echo "unknown process mode: ${mode}" >&2
        echo "supported modes: api" >&2
        exit 64
        ;;
esac
