"""NEXUS AGENT OS — Local Browser Bridge package.

The bridge is a separate local process that lets an agent drive the owner's own
signed-in browser tab through a Tampermonkey userscript. It runs as a FastAPI
service with a WebSocket endpoint. This is the deployment slice used by the
Docker stack (`infrastructure/docker/Dockerfile.bridge`).
"""
