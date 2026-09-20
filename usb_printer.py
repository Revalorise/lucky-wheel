"""ESC/POS USB printing helpers for an 80 mm thermal printer."""

import json
import os
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "printer_config.json")


def load_config():
    defaults = {
        "enabled": True, "vendor_id": "auto", "product_id": "auto",
        "paper_width_pixels": 576, "cut": True,
    }
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            defaults.update(json.load(handle))
    except (FileNotFoundError, ValueError):
        pass
    return defaults


def _number(value):
    if value in (None, "", "auto"):
        return None
    return int(str(value), 0)


def find_usb_printer(config):
    import usb.core
    import usb.util

    wanted_vendor = _number(config.get("vendor_id"))
    wanted_product = _number(config.get("product_id"))
    candidates = []
    for device in usb.core.find(find_all=True):
        if wanted_vendor is not None and device.idVendor != wanted_vendor:
            continue
        if wanted_product is not None and device.idProduct != wanted_product:
            continue
        product = ""
        try:
            product = usb.util.get_string(device, device.iProduct) or ""
        except Exception:
            pass
        is_printer = False
        try:
            is_printer = any(
                interface.bInterfaceClass == 7
                for configuration in device
                for interface in configuration
            )
        except Exception:
            pass
        name_matches = any(word in product.lower() for word in ("printer", "pos", "thermal"))
        # 0x0483 คือ STMicroelectronics ซึ่ง POS80 บางรุ่นรายงานเป็นชื่อนี้
        if wanted_vendor is not None or is_printer or name_matches or device.idVendor == 0x0483:
            candidates.append((device, product))
    if not candidates:
        raise RuntimeError(
            "ไม่พบ USB printer กรุณาตรวจสาย/ไฟ และกำหนด vendor_id กับ product_id จากคำสั่ง lsusb"
        )
    if len(candidates) > 1 and wanted_vendor is None:
        names = ", ".join(
            f"{device.idVendor:04x}:{device.idProduct:04x} {name}".strip()
            for device, name in candidates
        )
        raise RuntimeError(f"พบเครื่องพิมพ์มากกว่าหนึ่งเครื่อง กรุณากำหนด ID ใน printer_config.json: {names}")
    return candidates[0][0]


def find_bulk_endpoints(device):
    import usb.util

    try:
        configuration = device.get_active_configuration()
    except Exception:
        configuration = device[0]
    for interface in configuration:
        endpoints = list(interface)
        out_endpoint = next((endpoint.bEndpointAddress for endpoint in endpoints
                             if usb.util.endpoint_direction(endpoint.bEndpointAddress)
                             == usb.util.ENDPOINT_OUT), None)
        in_endpoint = next((endpoint.bEndpointAddress for endpoint in endpoints
                            if usb.util.endpoint_direction(endpoint.bEndpointAddress)
                            == usb.util.ENDPOINT_IN), None)
        if out_endpoint is not None:
            return in_endpoint or 0x82, out_endpoint
    return 0x82, 0x01


def print_image(image_path):
    from PIL import Image
    from escpos.printer import Usb

    config = load_config()
    if not config.get("enabled", True):
        return
    device = find_usb_printer(config)
    in_endpoint, out_endpoint = find_bulk_endpoints(device)
    printer = Usb(device.idVendor, device.idProduct, timeout=30000,
                  in_ep=in_endpoint, out_ep=out_endpoint)
    try:
        printer.set(align="center")
        with Image.open(image_path) as source:
            source = source.convert("1")
            top = 0
            while top < source.height:
                bottom = min(top + 128, source.height)
                fragment = source.crop((0, top, source.width, bottom))
                printer.image(fragment, impl="bitImageRaster", fragment_height=fragment.height)
                top = bottom
                time.sleep(0.12)
        printer._raw(b"\n\n\n")
        if config.get("cut", True):
            printer.cut()
    finally:
        printer.close()
