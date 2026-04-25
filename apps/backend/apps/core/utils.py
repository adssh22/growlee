import base64
from html import escape
from io import BytesIO

import qrcode


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = (value or '').strip().lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    if len(value) != 6:
        return (17, 24, 39)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (17, 24, 39)


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    ratio = max(0, min(1, ratio))
    rgb = tuple(round(a[i] * (1 - ratio) + b[i] * ratio) for i in range(3))
    return '#%02x%02x%02x' % rgb


def generate_qr_data_uri(data: str, fill_color: str = '#0f172a', back_color: str = '#ffffff') -> str:
    qr = qrcode.QRCode(version=6, box_size=12, border=3, error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color=fill_color, back_color=back_color)
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def build_qr_svg(data: str, merchant_name: str, primary_color: str = '#111827', accent_color: str = '#22c55e', logo_url: str | None = None, size: int = 900) -> str:
    qr_fill = _mix(primary_color, '#020617', 0.20)
    accent = accent_color or '#22c55e'
    bg_dark = _mix(primary_color, '#020617', 0.56)
    qr_data_uri = generate_qr_data_uri(data, fill_color=qr_fill, back_color='#ffffff')
    safe_data = escape(data)
    safe_merchant_name = escape(merchant_name)
    initials = escape(''.join(part[:1] for part in merchant_name.split()[:2]).upper() or 'G')
    safe_logo_url = escape(logo_url) if logo_url else None

    if safe_logo_url:
        logo = f'<image href="{safe_logo_url}" x="376" y="376" width="148" height="148" preserveAspectRatio="xMidYMid meet" />'
    else:
        logo = f'<rect x="376" y="376" width="148" height="148" rx="34" fill="{accent}"/><text x="450" y="471" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="52" font-weight="900" fill="#07111f">{initials}</text>'

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 900 900">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="{primary_color}"/>
          <stop offset="1" stop-color="{bg_dark}"/>
        </linearGradient>
        <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="28" stdDeviation="24" flood-color="#000" flood-opacity=".30"/></filter>
      </defs>
      <rect width="900" height="900" rx="46" fill="url(#bg)"/>
      <circle cx="95" cy="96" r="210" fill="{accent}" opacity=".18"/>
      <circle cx="820" cy="790" r="250" fill="#fff" opacity=".08"/>

      <text x="450" y="86" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="20" font-weight="900" letter-spacing="4" fill="rgba(255,255,255,.62)">GROWLEE</text>
      <text x="450" y="146" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="58" font-weight="900" letter-spacing="-2" fill="#fff">{safe_merchant_name}</text>
      <text x="450" y="188" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="24" font-weight="600" fill="rgba(255,255,255,.78)">Scannez pour jouer et récupérer votre gain</text>

      <g filter="url(#shadow)">
        <rect x="110" y="230" width="680" height="520" rx="56" fill="#fff"/>
        <image href="{qr_data_uri}" x="154" y="274" width="592" height="432" preserveAspectRatio="xMidYMid meet" />
        <rect x="358" y="358" width="184" height="184" rx="44" fill="#fff"/>
        {logo}
      </g>

      <rect x="176" y="778" width="548" height="74" rx="28" fill="{accent}"/>
      <text x="450" y="825" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="900" fill="#07111f">SCANNEZ · JOUEZ · GAGNEZ</text>
      <text x="450" y="878" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="12" font-weight="700" fill="rgba(255,255,255,.45)">{safe_data}</text>
    </svg>'''
