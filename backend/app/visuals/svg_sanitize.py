"""lxml-based SVG sanitizer.

All LLM output is untrusted (SPEC §5 / CLAUDE.md invariant #2): SVG returned by the Claude-SVG
generator is parsed and hardened on the server before it is ever stored or served. The client also
DOMPurifies on render — this is the server half of that defence-in-depth.

Rejections (raise :class:`SvgSanitizeError`):
  * ``<script>`` / ``<foreignObject>`` elements (script injection, HTML smuggling),
  * any ``on*`` event-handler attribute,
  * external / unsafe ``href`` / ``xlink:href`` values (anything not a same-document ``#id`` fragment),
  * ``<a>`` links and embedded ``<image>`` / ``<use>`` referencing external resources,
  * missing ``viewBox`` on the root ``<svg>`` (required for responsive, safe scaling),
  * payloads larger than :data:`~app.core.constants.SVG_MAX_BYTES`.

The returned string is the serialised, cleaned SVG.
"""

from __future__ import annotations

from lxml import etree

from ..core.constants import SVG_MAX_BYTES

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

# Elements that can execute script, smuggle HTML, or pull external resources. ``style`` is forbidden
# because <style> CSS can pull external url()/@import (children's diagrams use presentation attributes
# / inline fills, never <style> blocks) — the per-element loop only inspects the style= attribute.
_FORBIDDEN_TAGS = frozenset({"script", "foreignobject", "iframe", "object", "embed", "audio", "video", "set", "animate", "handler", "style"})

# Attributes that can navigate or load remote content; href values are validated, the rest are dropped.
_URL_ATTRS = frozenset({"href", f"{{{XLINK_NS}}}href"})


class SvgSanitizeError(ValueError):
    """Raised when an SVG cannot be made safe (forbidden node, missing viewBox, too large, unparseable)."""


def _localname(tag: object) -> str:
    """Lower-cased local element name, namespace-stripped. Comments/PIs have non-str tags."""
    if not isinstance(tag, str):
        return ""
    return etree.QName(tag).localname.lower() if "}" in tag else tag.lower()


def _href_is_safe(value: str) -> bool:
    """Only same-document fragment references (``#some-id``) are allowed for href/xlink:href."""
    return value.strip().startswith("#")


def sanitize_svg(svg: str | bytes, *, max_bytes: int = SVG_MAX_BYTES) -> str:
    """Parse, validate and re-serialise ``svg``; raise :class:`SvgSanitizeError` if it cannot be made safe."""
    if svg is None:
        raise SvgSanitizeError("empty SVG")

    raw = svg.encode("utf-8") if isinstance(svg, str) else svg
    if not raw.strip():
        raise SvgSanitizeError("empty SVG")
    if len(raw) > max_bytes:
        raise SvgSanitizeError(f"SVG too large: {len(raw)} bytes > {max_bytes}")

    # resolve_entities=False + no_network=True block XXE / billion-laughs / external entity fetches.
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
        dtd_validation=False,
        load_dtd=False,
    )
    try:
        root = etree.fromstring(raw, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise SvgSanitizeError(f"unparseable SVG: {exc}") from exc

    if root.getroottree().docinfo.doctype:
        # A DOCTYPE on an SVG is a classic entity-expansion / SSRF vector.
        raise SvgSanitizeError("SVG must not declare a DOCTYPE")

    if _localname(root.tag) != "svg":
        raise SvgSanitizeError("root element is not <svg>")

    if root.get("viewBox") is None and root.get("viewbox") is None:
        raise SvgSanitizeError("SVG root must declare a viewBox")

    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str):  # comment / PI already removed, but be defensive
            continue
        local = _localname(tag)
        if local in _FORBIDDEN_TAGS:
            raise SvgSanitizeError(f"forbidden element: <{local}>")

        for attr_name in list(el.attrib):
            local_attr = etree.QName(attr_name).localname.lower() if "}" in attr_name else attr_name.lower()
            value = el.attrib[attr_name]

            # Event handlers (onload, onclick, ...) are never allowed.
            if local_attr.startswith("on"):
                raise SvgSanitizeError(f"forbidden event-handler attribute: {local_attr}")

            # href / xlink:href must be same-document fragments only.
            if (attr_name in _URL_ATTRS or local_attr == "href") and not _href_is_safe(value):
                raise SvgSanitizeError(f"forbidden external reference in {local_attr}: {value!r}")

            # style attributes can smuggle url()/expression(); drop any that reference a URL or js.
            if local_attr == "style":
                lowered = value.lower()
                if "url(" in lowered or "javascript:" in lowered or "expression(" in lowered:
                    raise SvgSanitizeError("forbidden url()/javascript in style attribute")

    cleaned = etree.tostring(root, encoding="unicode")

    # Re-check size after normalisation (entity expansion / pretty-print should never grow it past cap).
    if len(cleaned.encode("utf-8")) > max_bytes:
        raise SvgSanitizeError("sanitized SVG exceeds size cap")

    return cleaned
