import io
import os
import re
from typing import Optional

import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS, IFD

st.set_page_config(page_title="Exif Studio : v1.2 — Photo Metadata Overlay", layout="wide")

st.markdown(
    """
    <style>
    .main { background-color: #000000; color: #d2d2d2; }
    section[data-testid="stSidebar"] {
        background-color: #050505;
        border-right: 1px solid #111;
    }
    .stButton>button, .stDownloadButton>button {
        background-color: #171717;
        color: #d9d9d9;
        border: 1px solid #333;
    }
    .stTextInput label, .stSelectbox label, .stSlider label,
    .stMultiSelect label, .stToggle label {
        color: #d6d6d6 !important;
    }
    .info-box {
        background: #0d0d0d;
        border: 1px solid #232323;
        border-radius: 10px;
        padding: 12px;
        color: #d9d9d9;
        line-height: 1.55;
        word-break: break-word;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# Fonts
# Put these files in repo:
# fonts/DejaVuSans.ttf
# fonts/DejaVuSansCondensed.ttf
# fonts/Rajdhani-Light.ttf
# fonts/RobotoCondensed-Light.ttf
# fonts/RobotoCondensed-Regular.ttf
# ------------------------------------------------------------
FONT_FILES = {
    "Rail Thin": "fonts/RobotoCondensed-Light.ttf",
    "Rail Regular": "fonts/RobotoCondensed-Regular.ttf",
    "Title Thin": "fonts/Rajdhani-Light.ttf",
    "Title Regular": "fonts/DejaVuSans.ttf",
}

FALLBACK_FONT = "fonts/DejaVuSans.ttf"

FIELD_LABELS = {
    "model": "Camera",
    "lens": "Lens",
    "focal": "Focal Length",
    "fstop": "Aperture",
    "shutter": "Shutter",
    "iso": "ISO",
    "datetime": "Date Time",
    "gps": "GPS Coordinates",
}

DEFAULT_FIELDS = ["model", "focal", "fstop", "iso"]

PRESETS = {
    "Leica Rail": {
        "layout": "Left Rail",
        "rail_font": "Rail Thin",
        "title_font": "Title Thin",
        "location_tracking": 1,
        "exif_tracking": 0,
        "rail_text_scale": 0.95,
        "rail_width_ratio": 0.028,
        "bar_text_scale": 0.018,
        "bar_height_ratio": 0.045,
        "location_size": 42,
        "subtitle_size": 22,
        "metadata_text_color": "#B0B0B0",
        "metadata_bg_color": "#000000",
        "location_text_color": "#F7F7F7",
        "subtitle_text_color": "#D8D8D8",
        "location_opacity": 0.88,
        "safe_ratio": 0.94,
        "top_margin": 0.030,
        "title_gap": 12,
        "show_top_plate": False,
        "top_plate_opacity": 0.16,
        "show_text_shadow": True,
        "show_divider": False,
    },
    "Sony Royal": {
        "layout": "Bottom Bar",
        "rail_font": "Rail Regular",
        "title_font": "Title Thin",
        "location_tracking": 2,
        "exif_tracking": 0,
        "rail_text_scale": 1.00,
        "rail_width_ratio": 0.030,
        "bar_text_scale": 0.020,
        "bar_height_ratio": 0.050,
        "location_size": 34,
        "subtitle_size": 18,
        "metadata_text_color": "#9A9A9A",
        "metadata_bg_color": "#000000",
        "location_text_color": "#FFFFFF",
        "subtitle_text_color": "#D5D5D5",
        "location_opacity": 0.90,
        "safe_ratio": 0.92,
        "top_margin": 0.025,
        "title_gap": 10,
        "show_top_plate": True,
        "top_plate_opacity": 0.18,
        "show_text_shadow": True,
        "show_divider": False,
    },
}

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def get_font(size: int, font_key: str) -> ImageFont.FreeTypeFont:
    path = FONT_FILES.get(font_key, FALLBACK_FONT)
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(FALLBACK_FONT, size)
        except Exception:
            return ImageFont.load_default()


def ratio_to_float(v) -> Optional[float]:
    try:
        if isinstance(v, tuple) and len(v) == 2 and v[1] != 0:
            return v[0] / v[1]
        return float(v)
    except Exception:
        return None


def format_decimal(value, default="") -> str:
    v = ratio_to_float(value)
    if v is None:
        return default
    return str(int(v)) if abs(v - int(v)) < 0.05 else f"{v:.1f}"


def format_shutter(value) -> str:
    v = ratio_to_float(value)
    if v is None or v <= 0:
        return ""
    if v < 1:
        return f"1/{int(round(1 / v))}"
    return str(int(v)) if abs(v - int(v)) < 0.05 else f"{v:.1f}"


def dms_to_decimal(dms, ref) -> Optional[float]:
    try:
        d = ratio_to_float(dms[0])
        m = ratio_to_float(dms[1])
        s = ratio_to_float(dms[2])
        if d is None or m is None or s is None:
            return None
        result = d + (m / 60.0) + (s / 3600.0)
        if ref in ["S", "W"]:
            result *= -1
        return result
    except Exception:
        return None


def get_gps_string(gps_info) -> str:
    if not gps_info:
        return ""

    gps_data = {}
    for key, value in gps_info.items():
        gps_data[GPSTAGS.get(key, key)] = value

    lat = (
        dms_to_decimal(gps_data.get("GPSLatitude"), gps_data.get("GPSLatitudeRef"))
        if gps_data.get("GPSLatitude")
        else None
    )
    lon = (
        dms_to_decimal(gps_data.get("GPSLongitude"), gps_data.get("GPSLongitudeRef"))
        if gps_data.get("GPSLongitude")
        else None
    )

    if lat is None or lon is None:
        return ""

    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.5f}° {ns}   •   {abs(lon):.5f}° {ew}"


def apply_tracking(text: str, spacing: int) -> str:
    text = text.upper().replace("ALPHA", "α")
    if spacing <= 0:
        return text
    joiner = " " * spacing
    return joiner.join(list(text))


def hex_to_rgba(hex_color: str, opacity: float):
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        hex_color = "FFFFFF"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    a = max(0, min(255, int(255 * opacity)))
    return (r, g, b, a)


def safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def sanitize_filename_part(text: str) -> str:
    text = safe_text(text)
    if not text:
        return ""
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-_")
    return text.lower()


def build_export_filename(original_name: str, suffix: str = "exif-curated") -> str:
    base = os.path.splitext(original_name)[0]
    suffix = sanitize_filename_part(suffix) or "exif-curated"
    return f"{base}_{suffix}.jpg"


# ------------------------------------------------------------
# EXIF extraction
# ------------------------------------------------------------
def get_exif_precision(img):
    exif = img.getexif()
    tags_found = {}
    gps_text = ""

    if exif:
        for tag, val in exif.items():
            tags_found[TAGS.get(tag, tag)] = val

        for ifd_id in IFD:
            try:
                ifd = exif.get_ifd(ifd_id)
                if getattr(ifd_id, "name", "") == "GPSInfo":
                    gps_text = get_gps_string(ifd)
                for tag, val in ifd.items():
                    tags_found[TAGS.get(tag, tag)] = val
            except Exception:
                pass

        if not gps_text:
            try:
                gps_ifd_key = next((k for k, v in TAGS.items() if v == "GPSInfo"), None)
                if gps_ifd_key and gps_ifd_key in exif:
                    gps_text = get_gps_string(exif.get_ifd(gps_ifd_key))
            except Exception:
                pass

    parsed = {
        "model": safe_text(tags_found.get("Model", "")).upper(),
        "lens": safe_text(tags_found.get("LensModel", "")),
        "focal": format_decimal(tags_found.get("FocalLength", ""), ""),
        "fstop": format_decimal(tags_found.get("FNumber", ""), ""),
        "iso": safe_text(tags_found.get("ISOSpeedRatings", tags_found.get("PhotographicSensitivity", ""))),
        "shutter": format_shutter(tags_found.get("ExposureTime", "")),
        "datetime": safe_text(tags_found.get("DateTimeOriginal", tags_found.get("DateTime", ""))),
        "gps": gps_text,
    }

    score_fields = ["model", "lens", "focal", "fstop", "iso", "shutter", "datetime", "gps"]
    present = sum(1 for k in score_fields if safe_text(parsed.get(k, "")))

    if present >= 6:
        status = "FULL"
    elif present >= 2:
        status = "PARTIAL"
    else:
        status = "STRIPPED"

    return parsed, status, tags_found


# ------------------------------------------------------------
# Session state
# ------------------------------------------------------------
def init_field_state(parsed_meta: dict):
    for key in FIELD_LABELS.keys():
        state_key = f"field_{key}"
        if state_key not in st.session_state:
            st.session_state[state_key] = safe_text(parsed_meta.get(key, ""))


def init_text_state():
    defaults = {
        "top_location": "",
        "custom_subtitle": "",
        "show_gps_subtitle": False,
        "export_suffix": "exif-curated",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ------------------------------------------------------------
# Text building
# ------------------------------------------------------------
def make_field_value(key, values):
    raw = safe_text(values.get(key, ""))

    if key == "model":
        return raw
    if key == "lens":
        return raw
    if key == "focal":
        return f"{raw}MM" if raw else ""
    if key == "fstop":
        return f"F/{raw}" if raw else ""
    if key == "shutter":
        return f"{raw}S" if raw else ""
    if key == "iso":
        return f"ISO {raw}" if raw else ""
    if key == "datetime":
        return raw
    if key == "gps":
        return raw
    return ""


def build_exif_text(selected_fields, values):
    parts = []
    for key in selected_fields:
        value = make_field_value(key, values)
        if value:
            parts.append(value)
    return "   |   ".join(parts)


# ------------------------------------------------------------
# Fit helpers
# ------------------------------------------------------------
def fit_text(draw, text, max_width, start_size, font_key, min_size=8):
    size = start_size
    while size >= min_size:
        font = get_font(size, font_key)
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            return font, bbox
        size -= 1
    font = get_font(min_size, font_key)
    return font, draw.textbbox((0, 0), text, font=font)


# ------------------------------------------------------------
# Metadata renderers
# ------------------------------------------------------------
def render_bottom_bar(img, text, tracking, text_scale, bar_height_ratio, text_color, bar_color, safe_ratio, font_key):
    w, h = img.size
    bar_h = max(24, int(h * bar_height_ratio))
    canvas = ImageOps.expand(img, border=(0, 0, 0, bar_h), fill=bar_color)
    draw = ImageDraw.Draw(canvas)

    final_text = apply_tracking(text, tracking)
    start_font_size = max(10, int(h * text_scale))
    safe_width = int(w * safe_ratio)
    font, bbox = fit_text(draw, final_text, safe_width, start_font_size, font_key)

    t_w = bbox[2] - bbox[0]
    t_h = bbox[3] - bbox[1]
    x = (w - t_w) // 2
    y = h + (bar_h // 2) - (t_h // 2)
    draw.text((x, y), final_text, fill=text_color, font=font)
    return canvas


def render_top_bar(img, text, tracking, text_scale, bar_height_ratio, text_color, bar_color, safe_ratio, font_key):
    w, h = img.size
    bar_h = max(24, int(h * bar_height_ratio))
    canvas = ImageOps.expand(img, border=(0, bar_h, 0, 0), fill=bar_color)
    draw = ImageDraw.Draw(canvas)

    final_text = apply_tracking(text, tracking)
    start_font_size = max(10, int(h * text_scale))
    safe_width = int(w * safe_ratio)
    font, bbox = fit_text(draw, final_text, safe_width, start_font_size, font_key)

    t_w = bbox[2] - bbox[0]
    t_h = bbox[3] - bbox[1]
    x = (w - t_w) // 2
    y = (bar_h // 2) - (t_h // 2)
    draw.text((x, y), final_text, fill=text_color, font=font)
    return canvas


def render_left_rail(img, text, tracking, rail_width_ratio, rail_text_scale, text_color, rail_color, safe_ratio, font_key):
    img = img.convert("RGB")
    w, h = img.size

    rail_w = max(20, int(w * rail_width_ratio))
    canvas = ImageOps.expand(img, border=(rail_w, 0, 0, 0), fill=rail_color)

    final_text = apply_tracking(text, tracking)

    text_img = Image.new("RGBA", (h, rail_w), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_img)

    font_size = max(10, int(rail_w * rail_text_scale))
    font = get_font(font_size, font_key)

    while font_size > 8:
        font = get_font(font_size, font_key)
        bbox = td.textbbox((0, 0), final_text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        fits_length = tw <= int(h * safe_ratio)
        fits_thickness = th <= int(rail_w * 0.80)

        if fits_length and fits_thickness:
            break

        font_size -= 1

    bbox = td.textbbox((0, 0), final_text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    tx = max(0, (h - tw) // 2)
    ty = max(0, (rail_w - th) // 2)
    td.text((tx, ty), final_text, fill=text_color, font=font)

    rotated = text_img.rotate(90, expand=True)
    px = 0
    py = (canvas.size[1] - rotated.size[1]) // 2
    canvas.paste(rotated, (px, py), rotated)

    return canvas


# ------------------------------------------------------------
# Top text renderer
# ------------------------------------------------------------
def render_top_text(
    canvas,
    title_text,
    subtitle_text,
    title_size,
    subtitle_size,
    title_color,
    subtitle_color,
    opacity,
    tracking,
    title_font_key,
    margin_ratio,
    title_gap,
    show_top_plate,
    top_plate_opacity,
    show_text_shadow,
    show_divider,
    position,
):
    if not safe_text(title_text) and not safe_text(subtitle_text):
        return canvas

    img = canvas.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = img.size
    margin = int(min(w, h) * margin_ratio)

    title = apply_tracking(safe_text(title_text), tracking) if safe_text(title_text) else ""
    subtitle = safe_text(subtitle_text)

    title_font = get_font(title_size, title_font_key)
    subtitle_font = get_font(subtitle_size, "Title Regular")

    title_bbox = draw.textbbox((0, 0), title, font=title_font) if title else (0, 0, 0, 0)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]

    sub_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font) if subtitle else (0, 0, 0, 0)
    sub_w = sub_bbox[2] - sub_bbox[0]
    sub_h = sub_bbox[3] - sub_bbox[1]

    total_h = 0
    if title:
        total_h += title_h
    if subtitle:
        total_h += sub_h
    if title and subtitle:
        total_h += title_gap
    if show_divider:
        total_h += max(8, subtitle_size // 2)

    if position == "Top Left":
        anchor_x_title = margin
        anchor_x_sub = margin
        align = "left"
    elif position == "Top Right":
        anchor_x_title = w - margin - title_w
        anchor_x_sub = w - margin - sub_w
        align = "right"
    else:
        anchor_x_title = (w - title_w) // 2
        anchor_x_sub = (w - sub_w) // 2
        align = "center"

    current_y = margin

    if show_top_plate:
        plate_padding_x = int(min(w, h) * 0.025)
        plate_padding_y = int(min(w, h) * 0.014)
        content_w = max(title_w, sub_w)
        if position == "Top Left":
            plate_x = max(0, anchor_x_title - plate_padding_x)
        elif position == "Top Right":
            plate_x = min(w - (content_w + plate_padding_x * 2), anchor_x_title - plate_padding_x)
        else:
            plate_x = (w - (content_w + plate_padding_x * 2)) // 2
        plate_w = content_w + plate_padding_x * 2
        plate_h = total_h + plate_padding_y * 2
        plate_y = max(0, current_y - plate_padding_y)
        draw.rounded_rectangle(
            [(plate_x, plate_y), (plate_x + plate_w, plate_y + plate_h)],
            radius=max(8, plate_padding_y),
            fill=(0, 0, 0, int(255 * top_plate_opacity)),
        )

    def draw_with_shadow(x, y, text, font, color_rgba):
        if show_text_shadow:
            shadow_offset = max(1, font.size // 18)
            draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0, int(160 * opacity)))
        draw.text((x, y), text, font=font, fill=color_rgba)

    if title:
        draw_with_shadow(anchor_x_title, current_y, title, title_font, hex_to_rgba(title_color, opacity))
        current_y += title_h

    if title and subtitle:
        current_y += title_gap

    if subtitle:
        draw_with_shadow(anchor_x_sub, current_y, subtitle, subtitle_font, hex_to_rgba(subtitle_color, opacity * 0.92))
        current_y += sub_h

    if show_divider:
        line_y = current_y + max(6, subtitle_size // 3)
        line_width = max(title_w, sub_w, 140)
        if align == "left":
            x1 = margin
            x2 = margin + line_width
        elif align == "right":
            x1 = w - margin - line_width
            x2 = w - margin
        else:
            x1 = (w - line_width) // 2
            x2 = x1 + line_width
        draw.line((x1, line_y, x2, line_y), fill=hex_to_rgba(subtitle_color, opacity * 0.75), width=1)

    return Image.alpha_composite(img, overlay).convert("RGB")


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------
st.title("ExIF S T U D I O --> v1.2")
st.caption("Two looks only: Leica Rail and Sony Royal.")

uploaded_file = st.file_uploader("Upload image", type=["jpg", "jpeg", "png", "webp"])

if uploaded_file:
    img = ImageOps.exif_transpose(Image.open(uploaded_file)).convert("RGB")
    parsed_meta, exif_status, raw_tags = get_exif_precision(img)

    init_field_state(parsed_meta)
    init_text_state()

    with st.sidebar:
        st.header("1. Preset")
        preset_name = st.selectbox("Look", list(PRESETS.keys()), index=0)
        preset = PRESETS[preset_name]

        st.header("2. Export")
        st.text_input("Export suffix", key="export_suffix")
        export_filename = build_export_filename(uploaded_file.name, st.session_state["export_suffix"])

        st.header("3. Metadata Layout")
        layout = st.selectbox(
            "Metadata layout",
            ["Left Rail", "Bottom Bar", "Top Bar"],
            index=["Left Rail", "Bottom Bar", "Top Bar"].index(preset["layout"]),
        )
        exif_fields = st.multiselect(
            "Fields to show",
            options=list(FIELD_LABELS.keys()),
            default=DEFAULT_FIELDS,
            format_func=lambda x: FIELD_LABELS[x],
        )

        st.header("4. Metadata Values")
        st.caption("Manual values always work.")
        st.text_input("Camera", key="field_model")
        st.text_input("Lens", key="field_lens")
        st.text_input("Focal", key="field_focal")
        st.text_input("Aperture", key="field_fstop")
        st.text_input("Shutter", key="field_shutter")
        st.text_input("ISO", key="field_iso")
        st.text_input("Date Time", key="field_datetime")
        st.text_input("Latitude / Longitude", key="field_gps")

        st.header("5. Top Text")
        st.text_input("Title", key="top_location")
        top_text_position = st.selectbox("Title position", ["Top Center", "Top Left", "Top Right"], index=0)

        top_text_mode = st.selectbox(
            "Top text style",
            ["Title Only", "Title + Coordinates", "Title + Custom Subtitle", "Coordinates Only", "None"],
            index=0,
        )

        st.text_input("Custom subtitle", key="custom_subtitle")

        st.header("6. Typography")
        rail_font_key = st.selectbox(
            "Rail font",
            ["Rail Thin", "Rail Regular"],
            index=["Rail Thin", "Rail Regular"].index(preset["rail_font"]),
        )
        title_font_key = st.selectbox(
            "Title font",
            ["Title Thin", "Title Regular"],
            index=["Title Thin", "Title Regular"].index(preset["title_font"]),
        )
        location_tracking = st.slider("Location letter spacing", 0, 4, preset["location_tracking"])
        exif_tracking = st.slider("Metadata letter spacing", 0, 2, preset["exif_tracking"])
        rail_text_scale = st.slider("Rail text size", 0.50, 2.20, preset["rail_text_scale"], 0.05)
        rail_width_ratio = st.slider("Rail thickness", 0.018, 0.060, preset["rail_width_ratio"], 0.002)
        bar_text_scale = st.slider("Bar text size", 0.010, 0.040, preset["bar_text_scale"], 0.001)
        bar_height_ratio = st.slider("Bar height", 0.028, 0.080, preset["bar_height_ratio"], 0.002)
        location_size = st.slider("Location title size", 14, 100, preset["location_size"])
        subtitle_size = st.slider("Subtitle size", 10, 80, preset["subtitle_size"])
        title_gap = st.slider("Gap between title and subtitle", 4, 40, preset["title_gap"])

        st.header("7. Colors")
        metadata_text_color = st.color_picker("Metadata text color", preset["metadata_text_color"])
        metadata_bg_color = st.color_picker("Rail / bar color", preset["metadata_bg_color"])
        location_text_color = st.color_picker("Title color", preset["location_text_color"])
        subtitle_text_color = st.color_picker("Subtitle color", preset["subtitle_text_color"])
        location_opacity = st.slider("Top text opacity", 0.20, 1.00, preset["location_opacity"], 0.01)

        st.header("8. Styling")
        show_top_plate = st.toggle("Soft dark plate", value=preset["show_top_plate"])
        top_plate_opacity = st.slider("Plate opacity", 0.00, 0.50, preset["top_plate_opacity"], 0.01)
        show_text_shadow = st.toggle("Soft text shadow", value=preset["show_text_shadow"])
        show_divider = st.toggle("Thin divider line", value=preset["show_divider"])

        st.header("9. Spacing")
        safe_ratio = st.slider("Text safe width", 0.70, 0.98, preset["safe_ratio"], 0.01)
        top_margin = st.slider("Top margin", 0.01, 0.08, preset["top_margin"], 0.005)

    values = {
        "model": safe_text(st.session_state.get("field_model", "")),
        "lens": safe_text(st.session_state.get("field_lens", "")),
        "focal": safe_text(st.session_state.get("field_focal", "")),
        "fstop": safe_text(st.session_state.get("field_fstop", "")),
        "shutter": safe_text(st.session_state.get("field_shutter", "")),
        "iso": safe_text(st.session_state.get("field_iso", "")),
        "datetime": safe_text(st.session_state.get("field_datetime", "")),
        "gps": safe_text(st.session_state.get("field_gps", "")),
    }

    top_title = safe_text(st.session_state.get("top_location", ""))
    gps_text = values["gps"]
    custom_subtitle = safe_text(st.session_state.get("custom_subtitle", ""))

    if top_text_mode == "Title Only":
        render_title = top_title
        final_subtitle = ""

    elif top_text_mode == "Title + Coordinates":
        render_title = top_title
        final_subtitle = gps_text

    elif top_text_mode == "Title + Custom Subtitle":
        render_title = top_title
        final_subtitle = custom_subtitle

    elif top_text_mode == "Coordinates Only":
        render_title = ""
        final_subtitle = gps_text

    else:  # None
        render_title = ""
        final_subtitle = ""

    exif_text = build_exif_text(exif_fields, values)

    if layout == "Left Rail":
        output = render_left_rail(
            img,
            exif_text,
            exif_tracking,
            rail_width_ratio,
            rail_text_scale,
            metadata_text_color,
            metadata_bg_color,
            safe_ratio,
            rail_font_key,
        )
    elif layout == "Bottom Bar":
        output = render_bottom_bar(
            img,
            exif_text,
            exif_tracking,
            bar_text_scale,
            bar_height_ratio,
            metadata_text_color,
            metadata_bg_color,
            safe_ratio,
            rail_font_key,
        )
    else:
        output = render_top_bar(
            img,
            exif_text,
            exif_tracking,
            bar_text_scale,
            bar_height_ratio,
            metadata_text_color,
            metadata_bg_color,
            safe_ratio,
            rail_font_key,
        )

    output = render_top_text(
        output,
        render_title,
        final_subtitle,
        location_size,
        subtitle_size,
        location_text_color,
        subtitle_text_color,
        location_opacity,
        location_tracking,
        title_font_key,
        top_margin,
        title_gap,
        show_top_plate,
        top_plate_opacity,
        show_text_shadow,
        show_divider,
        top_text_position,
    )

    left, right = st.columns([1.3, 0.7])

    with left:
        st.image(output, use_container_width=True)

    with right:
        st.markdown(
            f'<div class="info-box"><b>EXIF Integrity</b><br>{exif_status}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="info-box"><b>Export file</b><br>{export_filename}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="info-box"><b>Metadata on image</b><br>{exif_text if exif_text else "Nothing selected"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="info-box"><b>Top title</b><br>{render_title if render_title else "Not set"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="info-box"><b>Top subtitle</b><br>{final_subtitle if final_subtitle else "Not set"}</div>',
            unsafe_allow_html=True,
        )

        with st.expander("Parsed EXIF"):
            st.json(parsed_meta)

        with st.expander("Raw EXIF tags"):
            st.json({str(k): str(v) for k, v in raw_tags.items()})

    buf = io.BytesIO()
    output.save(buf, format="JPEG", quality=100, subsampling=0)

    st.download_button(
        label=f"⚡ Export {export_filename}",
        data=buf.getvalue(),
        file_name=export_filename,
        mime="image/jpeg",
        use_container_width=True,
    )

else:
    st.info("Upload one image. If EXIF is missing, type values manually in the sidebar and they will be used in preview and download.")