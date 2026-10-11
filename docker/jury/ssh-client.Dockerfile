FROM alpine:3.24.2@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

RUN apk add --no-cache openssh-client-default=10.3_p1-r1 \
    && adduser -D -H -u 10001 tunnel

USER 10001:10001
ENTRYPOINT ["ssh"]
