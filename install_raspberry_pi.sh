#!/bin/bash
set -e

sudo apt update
sudo apt install -y python3 python3-pygame python3-gpiozero python3-pil \
  python3-usb python3-serial python3-pip fonts-tlwg

python3 -m pip install --break-system-packages "python-escpos[usb]>=3.1,<4"

# อนุญาตให้ผู้ใช้ปัจจุบันเปิด USB printer โดยไม่ต้องรันเกมด้วย sudo
sudo usermod -aG lp "$USER"
echo 'SUBSYSTEM=="usb", ATTR{bInterfaceClass}=="07", MODE="0660", GROUP="lp"' \
  | sudo tee /etc/udev/rules.d/99-escpos-printer.rules >/dev/null
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="0483", MODE="0660", GROUP="lp"' \
  | sudo tee -a /etc/udev/rules.d/99-escpos-printer.rules >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "ติดตั้งเสร็จแล้ว กรุณาออกจากระบบแล้วเข้าใหม่หนึ่งครั้ง จากนั้นใช้ ./run_raspberry_pi.sh"
