"""Offline tests for the B3 visual pipeline.

No network: the Claude-SVG client and the Replicate runner are mocked. Covers cache hit/miss,
content-hash stability, SVG sanitization (strips <script>/on*), atomic disk write, and graceful
placeholder degradation on provider failure. Imports stay within the B3 module + the frozen spine.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import VisualAsset
from app.schemas.enums import LayoutSlot, VisualKind
from app.schemas.generation import GenVisualSpec
from app.visuals import cache, claude_svg, ensure_visual, replicate_raster
from app.visuals.svg_sanitize import SvgSanitizeError, sanitize_svg

VALID_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect width="100" height="100" fill="#cde"/><circle cx="50" cy="50" r="20" fill="#36c"/>'
    "</svg>"
)


def _is_file(path: str | None) -> bool:
    return bool(path) and Path(path).is_file()


def _read_file(path: str) -> bytes:
    return Path(path).read_bytes()


# --------------------------------------------------------------------------- DB fixture (in-memory)
@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    """Point the visual cache dir at a per-test tmp dir and clear any DI overrides."""
    from app.core.config import settings

    monkeypatch.setattr(type(settings), "visual_cache_dir", property(lambda self: tmp_path / "visuals"))
    claude_svg.set_svg_client(None)
    replicate_raster.set_replicate_runner(None)
    yield
    claude_svg.set_svg_client(None)
    replicate_raster.set_replicate_runner(None)


# --------------------------------------------------------------------------- fakes
class FakeSvgClient:
    """Stands in for app.llm.client: returns a structured SvgGenerationOutput."""

    def __init__(self, svg: str = VALID_SVG, alt: str = "a blue circle", caption: str | None = "Figure 1"):
        self.svg, self.alt, self.caption, self.calls = svg, alt, caption, 0

    async def parse(self, *, system, user, output_format):  # noqa: ANN001
        self.calls += 1
        return output_format(svg=self.svg, alt=self.alt, caption=self.caption)


def make_runner(data: bytes = b"\x52\x49\x46\x46webpfake"):
    calls = {"n": 0}

    async def runner(ref, *, input):  # noqa: A002,ANN001
        calls["n"] += 1
        return data

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def svg_spec(**kw) -> GenVisualSpec:
    base = {
        "section_ordinal": 1,
        "visual_kind": VisualKind.DIAGRAM,
        "layout_slot": LayoutSlot.INLINE_FIGURE,
        "svg_request": "draw the water cycle",
        "alt_text": "the water cycle",
        "caption": None,
    }
    base.update(kw)
    return GenVisualSpec(**base)


def raster_spec(**kw) -> GenVisualSpec:
    base = {
        "section_ordinal": 2,
        "visual_kind": VisualKind.ILLUSTRATION,
        "layout_slot": LayoutSlot.HERO,
        "image_prompt": "a happy sun over green hills",
        "alt_text": "a sun over hills",
        "caption": None,
    }
    base.update(kw)
    return GenVisualSpec(**base)


# --------------------------------------------------------------------------- svg_sanitize
def test_sanitize_accepts_valid_svg():
    out = sanitize_svg(VALID_SVG)
    assert "<svg" in out and "viewBox" in out


def test_sanitize_strips_rejects_script():
    bad = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<script>alert(1)</script><rect width="10" height="10"/></svg>'
    )
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(bad)


def test_sanitize_rejects_onload_handler():
    bad = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="evil()">'
        '<rect width="10" height="10"/></svg>'
    )
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(bad)


def test_sanitize_rejects_external_href():
    bad = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'viewBox="0 0 10 10"><image xlink:href="http://evil.test/x.png"/></svg>'
    )
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(bad)


def test_sanitize_allows_fragment_href():
    ok = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'viewBox="0 0 10 10"><use xlink:href="#sym"/></svg>'
    )
    assert "<svg" in sanitize_svg(ok)


def test_sanitize_requires_viewbox():
    with pytest.raises(SvgSanitizeError):
        sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')


def test_sanitize_rejects_foreignobject():
    bad = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<foreignObject><div>x</div></foreignObject></svg>"
    )
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(bad)


def test_sanitize_rejects_oversize():
    big = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        + "<rect/>" * 20000
        + "</svg>"
    )
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(big)


def test_sanitize_rejects_doctype_entities():
    bad = (
        '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect/></svg>'
    )
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(bad)


# --------------------------------------------------------------------------- content hash
def test_hash_stable_and_prompt_normalized():
    a = cache.compute_hash(
        asset_type="raster", model_id="m", model_version=None,
        prompt="A  Happy   SUN", params={"b": 1, "a": 2}, seed=0, output_format="webp",
    )
    b = cache.compute_hash(
        asset_type="raster", model_id="m", model_version=None,
        prompt="a happy sun", params={"a": 2, "b": 1}, seed=0, output_format="webp",
    )
    assert a == b  # NFC+lower+ws-collapse + sorted params → identical


def test_hash_changes_with_seed():
    base = {
        "asset_type": "raster", "model_id": "m", "model_version": None,
        "prompt": "x", "params": {}, "output_format": "webp",
    }
    assert cache.compute_hash(seed=1, **base) != cache.compute_hash(seed=2, **base)


def test_cache_path_sharding():
    h = "ab" + "c" * 62
    p = cache.cache_path(h, "webp")
    assert p.parent.name == h[2:4] and p.parent.parent.name == "ab"
    assert p.name == f"{h}.webp"


# --------------------------------------------------------------------------- atomic write
def test_atomic_write_creates_file_and_no_tmp_left(tmp_path):
    from app.core.config import settings

    h = "ff" + "0" * 62
    path = cache.write_bytes_atomic(h, b"hello", "webp")
    assert Path(path).read_bytes() == b"hello"
    leftovers = [p for p in Path(path).parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert str(settings.visual_cache_dir) in str(path)


# --------------------------------------------------------------------------- claude_svg generator
async def test_generate_svg_sanitizes_output():
    client = FakeSvgClient()
    claude_svg.set_svg_client(client)
    out = await claude_svg.generate_svg(svg_spec(), language="en", grade_band="G3-5")
    assert "<svg" in out["svg"] and out["alt"] == "a blue circle"
    assert client.calls == 1


async def test_generate_svg_raises_on_unsafe():
    bad = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 5"><script/></svg>'
    claude_svg.set_svg_client(FakeSvgClient(svg=bad))
    with pytest.raises(SvgSanitizeError):
        await claude_svg.generate_svg(svg_spec(), language="en", grade_band="G3-5")


# --------------------------------------------------------------------------- router: svg cache miss/hit
async def test_ensure_visual_svg_miss_then_hit(db):
    client = FakeSvgClient()
    claude_svg.set_svg_client(client)
    spec = svg_spec()

    a1 = await ensure_visual(db, spec, language="en", grade_band="G3-5")
    await db.flush()
    assert a1.asset_type == "svg"
    assert a1.svg_inline and "<svg" in a1.svg_inline
    assert _is_file(a1.file_path)
    assert client.calls == 1

    # Second call with identical inputs → cache hit, no new client call, hit_count bumped.
    a2 = await ensure_visual(db, spec, language="en", grade_band="G3-5")
    assert a2.hash == a1.hash
    assert client.calls == 1
    assert a2.hit_count >= 1

    count = len((await db.execute(select(VisualAsset))).scalars().all())
    assert count == 1


# --------------------------------------------------------------------------- router: raster persists bytes
async def test_ensure_visual_raster_persists_bytes(db):
    runner = make_runner(b"webp-bytes-123")
    replicate_raster.set_replicate_runner(runner)
    spec = raster_spec()

    a1 = await ensure_visual(db, spec, language="en", grade_band="G3-5")
    await db.flush()
    assert a1.asset_type == "raster"
    assert a1.mime == "image/webp"
    assert a1.svg_inline is None
    assert _read_file(a1.file_path) == b"webp-bytes-123"
    assert runner.calls["n"] == 1

    # Cache hit: identical spec → no second provider call.
    a2 = await ensure_visual(db, spec, language="en", grade_band="G3-5")
    assert a2.hash == a1.hash
    assert runner.calls["n"] == 1


# --------------------------------------------------------------------------- router: degrade on failure
async def test_ensure_visual_degrades_on_svg_failure(db):
    async def boom(*, system, user, output_format):  # noqa: ANN001
        raise RuntimeError("provider down")

    class Boom:
        parse = staticmethod(boom)

    claude_svg.set_svg_client(Boom())
    a = await ensure_visual(db, svg_spec(), language="en", grade_band="G3-5")
    assert a.asset_type == "svg"
    assert a.model == "placeholder"
    assert "<svg" in a.svg_inline


async def test_ensure_visual_degrades_on_raster_failure(db):
    async def boom(ref, *, input):  # noqa: A002,ANN001
        raise RuntimeError("replicate 500")

    replicate_raster.set_replicate_runner(boom)
    a = await ensure_visual(db, raster_spec(), language="en", grade_band="G3-5")
    # Raster provider failed → placeholder SVG so generation never hard-fails.
    assert a.model == "placeholder"
    assert a.svg_inline and "<svg" in a.svg_inline


# --------------------------------------------------------------------------- router: icon/decorative
async def test_ensure_visual_icon(db):
    spec = svg_spec(visual_kind=VisualKind.ICON, svg_request=None)
    a = await ensure_visual(db, spec, language="en", grade_band="K")
    assert a.asset_type == "svg_icon"
    assert a.svg_inline and "<svg" in a.svg_inline


# --------------------------------------------------------------------------- prompt safety: never raw text
def test_replicate_prompt_built_from_template_only():
    spec = raster_spec(image_prompt="a smiling planet earth")
    prompt = replicate_raster.build_prompt(spec, grade_band="G3-5")
    assert "a smiling planet earth" in prompt
    assert "children's textbook style" in prompt  # template scaffold present
    assert "Do not include" in prompt              # negative clause present
