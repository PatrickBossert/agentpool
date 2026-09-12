"""The agent portrait is downscaled and stripped on the way in.

`prepare_portrait` is driven directly here rather than through the upload door. It is a pure
function over bytes, and the properties that matter - the orientation flag is honoured, the
EXIF block is gone, a small portrait is left alone - are properties of the *bytes it returns*.
Asserting them one layer away, at a door that answers 200, would not distinguish a correct
implementation from a resize that always runs or a save that carries the metadata forward.

Each property gets a test of its own, deliberately. An image that is both rotated and carrying
GPS coordinates satisfies two separate assertions, and a single test over it would go green
while either half was broken.
"""

import io

import pytest
from PIL import Image

from api.services.image_intake import (
    MAX_PORTRAIT_BYTES,
    MAX_PORTRAIT_EDGE,
    PortraitRejected,
    _without_metadata,
    prepare_portrait,
)


def _encode(image: Image.Image, image_format: str, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, image_format, **options)
    return buffer.getvalue()


def _exif(orientation: int | None = None, with_gps: bool = False) -> Image.Exif:
    """EXIF as a phone writes it: an orientation flag, and where the photograph was taken."""
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    if with_gps:
        exif[0x8825] = {
            1: "N",
            2: (51.0, 30.0, 0.0),
            3: "W",
            4: (0.0, 7.0, 0.0),
        }
    return exif


def _phone_photograph(
    size: tuple[int, int] = (200, 100),
    orientation: int | None = 6,
    with_gps: bool = True,
) -> bytes:
    """A JPEG that is both rotated by metadata and carries the photographer's location."""
    return _encode(
        Image.new("RGB", size, "white"),
        "JPEG",
        exif=_exif(orientation=orientation, with_gps=with_gps),
    )


def _opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# --- Step 3: the downscale -------------------------------------------------------------


def test_a_large_portrait_is_downscaled_to_the_longest_side():
    big = Image.new("RGB", (3000, 2000), "white")
    out, ext = prepare_portrait(_encode(big, "JPEG"), "image/jpeg")
    assert _opened(out).size == (512, 341)  # aspect ratio preserved, not cropped
    assert ext == ".jpg"


def test_the_longest_side_is_the_one_bounded_when_the_portrait_is_taller_than_it_is_wide():
    """A portrait photograph is the ordinary case here, and bounding the width would leave it
    1024 tall. The rule is the longest side, whichever side that happens to be."""
    tall = Image.new("RGB", (2000, 3000), "white")
    out, _ = prepare_portrait(_encode(tall, "JPEG"), "image/jpeg")
    assert _opened(out).size == (341, 512)


def test_downscaling_never_crops_even_at_an_extreme_aspect_ratio():
    wide = Image.new("RGB", (4000, 250), "white")
    out, _ = prepare_portrait(_encode(wide, "PNG"), "image/png")
    width, height = _opened(out).size
    assert max(width, height) == MAX_PORTRAIT_EDGE
    # The stored aspect ratio is the one that came in, to within a pixel of rounding.
    assert abs((width / height) - (4000 / 250)) < 0.5


# --- Step 4: and never enlarges --------------------------------------------------------


def test_a_small_portrait_is_not_upscaled():
    """A resize that always runs would satisfy the test above and quietly blur every small
    portrait, so this is asserted separately rather than assumed from it."""
    small = Image.new("RGB", (200, 120), "white")
    out, _ = prepare_portrait(_encode(small, "PNG"), "image/png")
    assert _opened(out).size == (200, 120)


def test_a_portrait_exactly_at_the_limit_is_left_at_its_own_size():
    exact = Image.new("RGB", (MAX_PORTRAIT_EDGE, 300), "white")
    out, _ = prepare_portrait(_encode(exact, "PNG"), "image/png")
    assert _opened(out).size == (MAX_PORTRAIT_EDGE, 300)


# --- Step 5: orientation first, then nothing else -------------------------------------


def test_the_exif_orientation_flag_is_honoured():
    """Orientation 6 means "rotate this to display it", so a 200x100 frame is really a
    100x200 portrait. Ignore the flag and the portrait renders sideways."""
    out, _ = prepare_portrait(_phone_photograph(size=(200, 100), orientation=6), "image/jpeg")
    assert _opened(out).size == (100, 200)


def test_a_portrait_keeps_no_exif_and_therefore_no_location():
    out, _ = prepare_portrait(_phone_photograph(), "image/jpeg")
    assert not _opened(out).getexif()


def test_the_gps_coordinates_specifically_do_not_survive():
    """Named separately from the test above because this is the one that matters: the portrait
    is served from the interview page, which has no authentication by design, so surviving GPS
    coordinates would disclose where the photograph was taken to every participant."""
    before = _opened(_phone_photograph()).getexif().get_ifd(0x8825)
    assert before, "the fixture must actually carry GPS, or this test asserts nothing"

    out, _ = prepare_portrait(_phone_photograph(), "image/jpeg")
    assert not _opened(out).getexif().get_ifd(0x8825)


def test_orientation_is_honoured_before_the_metadata_is_discarded():
    """The two are ordered, not merely both present. Strip first and the rotation is gone
    before anything has acted on it, which reads as a working strip and a sideways portrait."""
    out, _ = prepare_portrait(_phone_photograph(size=(300, 150), orientation=6), "image/jpeg")
    stored = _opened(out)
    assert stored.size == (150, 300)
    assert not stored.getexif()


def test_the_image_handed_to_the_encoder_carries_no_metadata_of_any_kind():
    """The mechanism, not only the outcome - and the distinction is the point.

    Pillow's JPEG and PNG encoders happen to drop an EXIF block they were not explicitly given,
    so every assertion above passes just as well against an implementation that does not strip
    anything and merely relies on that default. This is the only test here that can tell the
    two apart. It is asserted because the default is the encoder's to change, and because a
    fourth format added to the allowlist need not share it - at which point the outcome tests
    would go on passing while GPS coordinates reached the interview page.
    """
    carrying = _opened(_phone_photograph())
    assert carrying.info.get("exif"), "the fixture must actually carry an EXIF block"

    stripped = _without_metadata(carrying)

    assert stripped.info == {}
    assert not stripped.getexif()
    assert stripped.size == carrying.size
    assert stripped.tobytes() == carrying.tobytes()  # the pixels are untouched


def test_metadata_is_discarded_from_a_png_too():
    """The strip must not be a property of one encoder's defaults."""
    data = _encode(
        Image.new("RGB", (120, 90), "white"), "PNG", exif=_exif(with_gps=True)
    )
    assert _opened(data).getexif(), "the fixture must actually carry EXIF"

    out, _ = prepare_portrait(data, "image/png")
    assert not _opened(out).getexif()


# --- Step 6: a ceiling, and a decoder that is not trusted with the label ---------------


def test_a_payload_above_the_ceiling_is_refused_and_the_message_names_the_limit():
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_PORTRAIT_BYTES
    with pytest.raises(PortraitRejected) as refusal:
        prepare_portrait(oversized, "image/png")
    assert "10 MB" in str(refusal.value)


def test_the_ceiling_is_applied_before_the_decoder_sees_the_bytes():
    """Downscaling is not a reason to accept an unbounded upload. The refusal above is raised
    against bytes that are not a decodable image at all, so it cannot have come from Pillow."""
    oversized = b"\x00" * (MAX_PORTRAIT_BYTES + 1)
    with pytest.raises(PortraitRejected) as refusal:
        prepare_portrait(oversized, "image/png")
    assert "size" in str(refusal.value)


def test_a_payload_of_exactly_the_ceiling_is_not_refused_for_its_size():
    """The limit is a ceiling, not a boundary one byte below it."""
    with pytest.raises(PortraitRejected) as refusal:
        prepare_portrait(b"\x00" * MAX_PORTRAIT_BYTES, "image/png")
    assert "size" not in str(refusal.value)


def test_a_payload_that_is_not_an_image_at_all_is_refused():
    with pytest.raises(PortraitRejected):
        prepare_portrait(b"this is not an image", "image/png")


def test_a_payload_that_is_not_the_type_it_declares_is_refused():
    """Pillow decodes by sniffing, so it reads a PNG happily whatever the request called it.
    The declared type decides the extension the file is stored under and how it is later
    served, so a disagreement is refused rather than quietly resolved in either direction."""
    png = _encode(Image.new("RGB", (100, 100), "white"), "PNG")
    with pytest.raises(PortraitRejected) as refusal:
        prepare_portrait(png, "image/jpeg")
    assert "image/jpeg" in str(refusal.value)


def test_a_content_type_outside_the_allowlist_is_refused():
    gif = _encode(Image.new("P", (50, 50)), "GIF")
    with pytest.raises(PortraitRejected) as refusal:
        prepare_portrait(gif, "image/gif")
    assert "image/gif" in str(refusal.value)


# --- The stored file answers to the type it was declared as ---------------------------


@pytest.mark.parametrize(
    "content_type,image_format,extension",
    [
        ("image/png", "PNG", ".png"),
        ("image/jpeg", "JPEG", ".jpg"),
        ("image/webp", "WEBP", ".webp"),
    ],
)
def test_the_stored_portrait_keeps_its_format_and_reports_its_extension(
    content_type, image_format, extension
):
    data = _encode(Image.new("RGB", (900, 600), "white"), image_format)
    out, ext = prepare_portrait(data, content_type)
    assert ext == extension
    assert _opened(out).format == image_format
    assert _opened(out).size == (512, 341)


def test_a_transparent_portrait_keeps_its_alpha_channel():
    """A cut-out portrait on a transparent background is the ordinary shape for this field, and
    flattening it onto black would be a visible regression rather than a silent one."""
    rgba = Image.new("RGBA", (800, 800), (255, 0, 0, 0))
    out, _ = prepare_portrait(_encode(rgba, "PNG"), "image/png")
    stored = _opened(out)
    assert stored.mode == "RGBA"
    assert stored.getpixel((0, 0))[3] == 0


def test_a_palette_portrait_is_accepted_rather_than_refused_by_the_encoder():
    palette = Image.new("RGB", (700, 700), "white").convert("P")
    out, _ = prepare_portrait(_encode(palette, "PNG"), "image/png")
    assert _opened(out).size == (512, 512)
