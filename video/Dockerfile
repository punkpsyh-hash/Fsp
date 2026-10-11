FROM mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27
WORKDIR /video
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY video/package*.json ./
RUN npm ci --no-audit --no-fund
COPY video/src ./src
COPY video/tsconfig.json ./
COPY docs/delivery/demo-final.mp4 ./public/source.mp4
RUN mkdir -p public/source-frames && ffmpeg -hide_banner -loglevel error -i public/source.mp4 -fps_mode passthrough -compression_level 1 public/source-frames/frame-%06d.png
COPY resources/DejaVuSans.ttf ./public/DejaVuSans.ttf
ENV HOME=/tmp
CMD ["npm", "run", "render"]
