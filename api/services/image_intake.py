"""Preparing an uploaded portrait for storage.

`prepare_portrait` is a pure function over bytes - no HTTP, no filesystem, no project - so
every property it holds can be driven directly rather than through a door. CLAUDE.md records
three guards whose reach could not be established because they only ever ran against real
inputs; this one is built the other way round.

Two of its properties are about privacy rather than tidiness, and both concern the same fact:
an agent portrait is served from the interview page, which has **no authentication at all** by
design, because a participant has no login. So a photograph taken on a phone and uploaded here
is world-readable, and a phone photograph carries EXIF.

- The orientation flag is honoured *first* (`ImageOps.exif_transpose`). Ignore it and the
  portrait renders sideways, because the rotation lives in the metadata rather than the pixels.
- Everything else in the metadata is then discarded, by rebuilding the image from its raw
  pixel bytes. GPS coordinates are the reason: keeping them serves the photographer's home or
  office address to every interviewee, on an engagement whose documents and inference may be
  deliberately on-premises. Rebuilding rather than "saving without EXIF" is the point - it is
  the encoder's default today that drops the block, and a default is not a guarantee.

The order matters and is not interchangeable: strip first and the orientation is gone before
anything has acted on it.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# The longest side any stored portrait may have. The largest portrait the product renders is
# `w-40` - 160 CSS pixels, 320 on a 2x display - so 512 is generous and the file stays small.
MAX_PORTRAIT_EDGE = 512

# A ceiling still applies. Downscaling is not a reason to accept an unbounded upload: the bytes
# are read into memory in full before Pillow is allowed to look at them.
MAX_PORTRAIT_BYTES = 10 * 1024 * 1024

# Declared content type -> the extension to store under, and the format Pillow must report when
# it decodes the payload. The second half of the pair is what makes this a check rather than a
# label: a decoder pointed at a file that is not the type it claims is the part of this path
# that is a security control.
PORTRAIT_CONTENT_TYPES: dict[str, tuple[str, str]] = {
    "image/png": (".png", "PNG"),
    "image/jpeg": (".jpg", "JPEG"),
    "image/webp": (".webp", "WEBP"),
}


class PortraitRejected(ValueError):
    """A payload that will not be stored, carrying a sentence fit to return to the caller.

    Distinguishable on purpose: a door catching this answers 422 and says why, while anything
    else escaping `prepare_portrait` is a defect here and should still be a 500.
    """


def _accepted_types_sentence() -> str:
    return ", ".join(sorted(PORTRAIT_CONTENT_TYPES))


def prepare_portrait(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Return the portrait to store and the extension to store it under.

    Raises `PortraitRejected` for a payload that is too large, of a type this path does not
    accept, or not a decodable image of the type it declares.
    """
    if content_type not in PORTRAIT_CONTENT_TYPES:
        raise PortraitRejected(
            f"Unsupported image type '{content_type}'. Must be one of {_accepted_types_sentence()}."
        )

    if len(data) > MAX_PORTRAIT_BYTES:
        raise PortraitRejected(
            f"Image exceeds the maximum allowed size of "
            f"{MAX_PORTRAIT_BYTES // (1024 * 1024)} MB."
        )

    extension, expected_format = PORTRAIT_CONTENT_TYPES[content_type]

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        # A decompression bomb decodes to far more pixels than its compressed size suggests, so
        # the byte ceiling above does not bound it. Pillow raises rather than allocating, and
        # that refusal belongs with the others rather than as a 500.
        raise PortraitRejected(
            f"File content is not a readable {expected_format} image."
        ) from exc

    if image.format != expected_format:
        # Pillow decodes by sniffing, so it will happily read a PNG that claims to be a JPEG.
        # The declared type decides where the file is stored and how it is later served, so a
        # disagreement is refused rather than silently resolved in either direction.
        raise PortraitRejected(
            f"File content does not match the declared content type '{content_type}'."
        )

    # Orientation first, while the flag still exists to be read.
    image = ImageOps.exif_transpose(image) or image

    image = _to_storable_mode(image, expected_format)
    image = _downscale(image)
    image = _without_metadata(image)

    buffer = io.BytesIO()
    save_options: dict[str, object] = {}
    if expected_format == "JPEG":
        save_options = {"quality": 88, "optimize": True}
    image.save(buffer, expected_format, **save_options)
    return buffer.getvalue(), extension


def _downscale(image: Image.Image) -> Image.Image:
    """Fit the image inside a `MAX_PORTRAIT_EDGE` square, preserving its aspect ratio.

    Never crops, and **never enlarges** - a 200px portrait stays 200px. A resize that always
    ran would satisfy the downscale property and quietly blur every small portrait, so the
    guard is a branch of its own rather than a consequence of the arithmetic.
    """
    width, height = image.size
    if max(width, height) <= MAX_PORTRAIT_EDGE:
        return image

    scale = MAX_PORTRAIT_EDGE / max(width, height)
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(target, Image.LANCZOS)


def _to_storable_mode(image: Image.Image, target_format: str) -> Image.Image:
    """Put the image in a mode its target format can hold and LANCZOS can resample well.

    Palette images resample badly and JPEG holds no alpha channel, so both are converted
    before the resize rather than left for the encoder to refuse.
    """
    if target_format == "JPEG":
        return image if image.mode in ("RGB", "L") else image.convert("RGB")
    if image.mode in ("RGB", "RGBA", "L"):
        return image
    return image.convert("RGBA")


def _without_metadata(image: Image.Image) -> Image.Image:
    """Return the same pixels carrying nothing else.

    Rebuilt from raw pixel bytes, so EXIF - and with it any GPS coordinates - cannot travel
    into the saved file by any route: not through `Image.info`, not through an encoder that
    decides to carry a block forward, and not through a format added to the allowlist later.
    """
    return Image.frombytes(image.mode, image.size, image.tobytes())
