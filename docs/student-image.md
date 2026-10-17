# Reproducing the student desktop image

The working API expects `linux-lab:1.0`, an existing custom desktop image. The provided source archive did not contain that image's original Dockerfile, package list or pinned base digest. The optional recipe in `student-image/` is a starter and does not claim to reproduce installed classroom applications.

## Preserve the working Pi image

Run on the Pi:

```bash
docker image inspect linux-lab:1.0 --format '{{.Os}}/{{.Architecture}} {{.Id}}'
docker image save linux-lab:1.0 | gzip > ~/linux-lab-image.tar.gz
```

Transfer privately with SCP. On a host with the same architecture:

```bash
gunzip -c linux-lab-image.tar.gz | docker image load
```

Do not commit this large archive or image layers to the repository. Inspect the image for embedded credentials or proprietary content before distributing it. This preserves image contents, not modifications inside a running student's container.

## Build an optional starter on a fresh host

From the repository root:

```bash
docker build -t linux-lab:starter student-image
```

Set `STUDENT_IMAGE=linux-lab:starter` in the test backend's `.env`, recreate the API, restart the proxy and run all acceptance tests. The floating base tag may change upstream. Once a base is validated, record its digest and rebuild with it:

```bash
docker build --build-arg WEBTOP_BASE='lscr.io/linuxserver/webtop@sha256:REPLACE_WITH_VALIDATED_DIGEST' -t linux-lab:1.0 student-image
```

LinuxServer Webtop supports amd64 and ARM64, but verify the exact chosen tag/digest and packages for your architecture. Build on each target architecture or publish a tested multi-platform image. Reconstruct and commit the original custom Dockerfile when available.

The application expects HTTP port 3000, `CUSTOM_USER`/`PASSWORD` authentication, `/config`, PUID/PGID 1000 and a desktop compatible with same-origin iframe rendering. Verify these assumptions whenever upgrading the image. Test the existing `no-new-privileges` setting against the classroom's package-installation exercises; do not silently relax isolation to make a new image work.

Reference: [Webtop image documentation](https://docs.linuxserver.io/images/docker-webtop/).
