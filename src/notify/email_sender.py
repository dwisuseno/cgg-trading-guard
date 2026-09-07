# src/notify/email_sender.py
"""
Pengiriman Daily Brief lewat email — opsional, aktif hanya jika kredensial
SMTP dikonfigurasi lewat Streamlit Secrets (App settings -> Secrets di
Streamlit Community Cloud) atau environment variable lokal. Modul ini
TIDAK PERNAH menyimpan atau meminta kredensial secara langsung -- ia hanya
membaca apa yang sudah dikonfigurasi pengguna sendiri di tempat yang aman.

Format secrets (.streamlit/secrets.toml, JANGAN pernah di-commit ke git):

    [smtp]
    host = "smtp.gmail.com"
    port = 465
    user = "akun-pengirim@gmail.com"
    password = "app-password-16-digit"
    to = "koordinator@cgg.co.id"
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from datetime import date


def _get_smtp_config():
    """Coba baca dari Streamlit secrets dulu, lalu fallback ke env var."""
    try:
        import streamlit as st
        if "smtp" in st.secrets:
            return dict(st.secrets["smtp"])
    except Exception:
        pass

    import os
    host = os.environ.get("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "to": os.environ.get("SMTP_TO"),
    }


def terkonfigurasi() -> bool:
    return _get_smtp_config() is not None


def kirim_email_brief(teks_brief: str, tanggal: date | None = None) -> tuple[bool, str]:
    """
    Mengirim brief sebagai email. Return (berhasil, pesan).
    Tidak pernah melempar exception ke pemanggil -- kegagalan jaringan/
    kredensial dikembalikan sebagai pesan, bukan crash aplikasi.
    """
    cfg = _get_smtp_config()
    if not cfg:
        return False, (
            "SMTP belum dikonfigurasi. Tambahkan lewat Streamlit Cloud: "
            "App settings -> Secrets, dengan format [smtp] host/port/user/password/to."
        )

    tanggal = tanggal or date.today()
    msg = MIMEText(teks_brief, "plain", "utf-8")
    msg["Subject"] = f"CGG Trading Guard — Daily Brief {tanggal.isoformat()}"
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), context=context, timeout=20) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["user"], [cfg["to"]], msg.as_string())
        return True, f"Terkirim ke {cfg['to']}"
    except Exception as e:
        return False, f"Gagal mengirim: {e}"
