# Generator image: the modulator's numpy, sox for the station and channel effects, and direwolf as the
# trusted decoder that proves every rendered capture can still be read.
FROM debian:trixie-slim
ENV PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-numpy sox libsox-fmt-all direwolf \
    && rm -rf /var/lib/apt/lists/*
