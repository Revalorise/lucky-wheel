import json
import math
import os
import queue
import secrets
import sys
import threading
import time
from datetime import datetime

import pygame

# --------------------------------------------------
# ตั้งค่าหลัก
# --------------------------------------------------
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

TOTAL_SECTORS = 60
SECTOR_ANGLE = 360 / TOTAL_SECTORS

PREDICTIONS_FILE = "predictions.json"
WHEEL_IMAGE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "wheel_pic.png",
)

# ใช้งาน GPIO หรือไม่
USE_GPIO = True

# หมายเลข GPIO แบบ BCM
GPIO_DAYS = {
    "วันจันทร์": 5,
    "วันอังคาร": 6,
    "วันพุธ": 13,
    "วันพฤหัสบดี": 16,
    "วันศุกร์": 17,
    "วันเสาร์": 18,
    "วันอาทิตย์": 19,
}
GPIO_SPIN = 20

# สี
BG_COLOR = (18, 24, 44)
PANEL_COLOR = (31, 42, 72)
TEXT_COLOR = (250, 250, 250)
SUBTEXT_COLOR = (190, 205, 230)
GOLD = (255, 202, 68)
RED = (220, 76, 76)
GREEN = (66, 180, 120)
BLUE = (73, 145, 235)
PURPLE = (151, 101, 220)
ORANGE = (242, 143, 72)

WHEEL_COLORS = [
    (231, 76, 60),
    (241, 196, 15),
    (46, 204, 113),
    (52, 152, 219),
    (155, 89, 182),
    (230, 126, 34),
]

DAYS = list(GPIO_DAYS.keys())

# --------------------------------------------------
# เครื่องมือ
# --------------------------------------------------
def find_thai_font():
    font_paths = [
        "/usr/share/fonts/truetype/tlwg/Loma.ttf",
        "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
        "/usr/share/fonts/truetype/tlwg/Kinnari.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for path in font_paths:
        if os.path.exists(path):
            return path

    return None


FONT_PATH = find_thai_font()


def get_font(size, bold=False):
    return pygame.font.Font(FONT_PATH, size) if FONT_PATH else pygame.font.SysFont(None, size, bold=bold)


def draw_text(surface, text, font, color, center_x, center_y):
    rendered = font.render(text, True, color)
    rect = rendered.get_rect(center=(center_x, center_y))
    surface.blit(rendered, rect)
    return rect


def draw_wrapped_text(surface, text, font, color, rect, line_spacing=8):
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        if font.size(test_line)[0] <= rect.width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    total_height = len(lines) * (font.get_height() + line_spacing) - line_spacing
    y = rect.centery - total_height // 2

    for line in lines:
        rendered = font.render(line, True, color)
        text_rect = rendered.get_rect(center=(rect.centerx, y + font.get_height() // 2))
        surface.blit(rendered, text_rect)
        y += font.get_height() + line_spacing


def load_predictions():
    if not os.path.exists(PREDICTIONS_FILE):
        raise FileNotFoundError(
            f"ไม่พบไฟล์ {PREDICTIONS_FILE} กรุณาสร้างไฟล์คำทำนายก่อนเปิดโปรแกรม"
        )

    with open(PREDICTIONS_FILE, "r", encoding="utf-8") as file:
        predictions = json.load(file)

    if len(predictions) != TOTAL_SECTORS:
        raise ValueError("ไฟล์ predictions.json ต้องมีคำทำนายทั้งหมด 60 รายการ")

    ids = sorted(item.get("id") for item in predictions)
    if ids != list(range(1, TOTAL_SECTORS + 1)):
        raise ValueError("id ใน predictions.json ต้องเรียงครบตั้งแต่ 1 ถึง 60")

    return predictions


# --------------------------------------------------
# ระบบ GPIO
# --------------------------------------------------
gpio_events = queue.Queue()


def setup_gpio():
    if not USE_GPIO:
        return None

    try:
        from gpiozero import Button

        devices = []

        for day, pin in GPIO_DAYS.items():
            button = Button(pin, pull_up=True, bounce_time=0.08)
            button.when_pressed = lambda d=day: gpio_events.put(("day", d))
            devices.append(button)

        spin_button = Button(GPIO_SPIN, pull_up=True, bounce_time=0.05)
        spin_button.when_pressed = lambda: gpio_events.put(("spin_down", None))
        spin_button.when_released = lambda: gpio_events.put(("spin_up", None))
        devices.append(spin_button)

        print("GPIO พร้อมใช้งาน")
        return devices

    except Exception as error:
        print(f"ไม่สามารถใช้งาน GPIO ได้: {error}")
        print("โปรแกรมยังใช้งานด้วยเมาส์หรือคีย์บอร์ดได้")
        return None


# --------------------------------------------------
# แอปพลิเคชัน
# --------------------------------------------------
class WheelFortuneApp:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Wheel of Fortune")

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()

        self.font_title = get_font(42)
        self.font_large = get_font(34)
        self.font_medium = get_font(25)
        self.font_small = get_font(18)

        self.predictions = load_predictions()

        # โหลดรูปวงล้อและตัดพื้นหลังลายตารางบริเวณมุมออกด้วยหน้ากากวงกลม
        wheel_size = 570
        wheel_image = pygame.image.load(WHEEL_IMAGE_FILE).convert_alpha()
        wheel_image = pygame.transform.smoothscale(
            wheel_image,
            (wheel_size, wheel_size),
        )
        circle_mask = pygame.Surface((wheel_size, wheel_size), pygame.SRCALPHA)
        pygame.draw.circle(
            circle_mask,
            (255, 255, 255, 255),
            (wheel_size // 2, wheel_size // 2),
            wheel_size // 2,
        )
        wheel_image.blit(circle_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.wheel_image = wheel_image

        self.selected_day = None
        self.state = "SELECT_DAY"

        # มุมของวงล้อ: เพิ่มขึ้น = หมุนตามเข็มนาฬิกา
        self.wheel_angle = 0.0
        self.spin_speed = 0.0
        self.is_holding_spin = False

        self.slow_start_angle = 0.0
        self.slow_target_angle = 0.0
        self.slow_start_time = 0.0
        self.slow_duration = 0.0

        self.result_index = None
        self.result_prediction = None
        self.result_printed = False
        self.print_status = ""

        self.day_buttons = []
        self.spin_button_rect = pygame.Rect(875, 565, 300, 80)
        self.reset_button_rect = pygame.Rect(915, 600, 220, 58)

        self.create_day_buttons()

    def create_day_buttons(self):
        self.day_buttons = []

        start_x = 790
        start_y = 170
        button_width = 190
        button_height = 52
        gap = 12

        for index, day in enumerate(DAYS):
            rect = pygame.Rect(
                start_x,
                start_y + index * (button_height + gap),
                button_width,
                button_height,
            )
            self.day_buttons.append((day, rect))

    def select_day(self, day):
        if self.state in ("SPINNING", "SLOWING"):
            return

        self.selected_day = day
        self.state = "READY"
        self.result_index = None
        self.result_prediction = None

    def start_spin(self):
        if self.state != "READY":
            return

        self.is_holding_spin = True
        self.state = "SPINNING"

    def release_spin(self):
        if self.state != "SPINNING" or not self.is_holding_spin:
            return

        self.is_holding_spin = False
        self.start_slow_down()

    def start_slow_down(self):
        # เลือกผลลัพธ์อย่างปลอดภัยจาก 0 ถึง 59
        self.result_index = secrets.randbelow(TOTAL_SECTORS)
        self.result_prediction = self.predictions[self.result_index]

        # จุดกึ่งกลางของช่องผลลัพธ์ต้องไปหยุดตรงเข็มด้านบน
        target_normalized = (-(self.result_index + 0.5) * SECTOR_ANGLE) % 360
        current_normalized = self.wheel_angle % 360

        delta = (target_normalized - current_normalized) % 360

        # เพิ่มรอบหมุนให้ดูเป็นธรรมชาติ
        extra_rounds = secrets.choice([5, 6, 7, 8])
        self.slow_start_angle = self.wheel_angle
        self.slow_target_angle = self.wheel_angle + delta + (extra_rounds * 360)

        # ยิ่งกดค้างนานและล้อเร็ว ระยะเวลาหยุดยิ่งยาวเล็กน้อย
        self.slow_duration = max(4.0, min(7.0, 4.0 + self.spin_speed / 180))
        self.slow_start_time = time.time()
        self.state = "SLOWING"

    def update(self, dt):
        if self.state == "SPINNING":
            # กดค้างแล้วความเร็วเพิ่มขึ้นจนถึงค่ากำหนด
            self.spin_speed = min(self.spin_speed + 420 * dt, 900)
            self.wheel_angle += self.spin_speed * dt

        elif self.state == "SLOWING":
            elapsed = time.time() - self.slow_start_time
            progress = min(elapsed / self.slow_duration, 1.0)

            # Cubic ease-out: เริ่มเร็วและช้าลงอย่างนุ่มนวล
            ease_out = 1 - pow(1 - progress, 3)

            self.wheel_angle = (
                self.slow_start_angle
                + (self.slow_target_angle - self.slow_start_angle) * ease_out
            )

            if progress >= 1.0:
                self.wheel_angle = self.slow_target_angle
                self.spin_speed = 0
                self.state = "RESULT"
                self.print_current_result()

    def create_receipt_image(self):
        """สร้างใบคำทำนายเป็นภาพ เพื่อให้เครื่องพิมพ์พิมพ์ภาษาไทยได้ครบ"""
        from PIL import Image, ImageFilter, ImageOps

        width = 576
        surface = pygame.Surface((width, 1200))
        surface.fill((255, 255, 255))
        title_font = get_font(34)
        heading_font = get_font(25)
        body_font = get_font(22)
        small_font = get_font(18)
        margin = 28
        content_width = width - margin * 2
        y = 28

        def centered(text, font, gap=10):
            nonlocal y
            rendered = font.render(str(text), True, (0, 0, 0))
            surface.blit(rendered, rendered.get_rect(midtop=(width // 2, y)))
            y += rendered.get_height() + gap

        def paragraph(text, font=body_font, gap=14):
            nonlocal y
            words = str(text).split()
            lines, current = [], ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if font.size(candidate)[0] <= content_width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            for line in lines or [""]:
                rendered = font.render(line, True, (0, 0, 0))
                surface.blit(rendered, (margin, y))
                y += font.get_linesize() + 3
            y += gap

        centered("เซียมซีระบบปฏิทินจีน", title_font, 8)
        pygame.draw.line(surface, (0, 0, 0), (margin, y), (width - margin, y), 2)
        y += 18
        paragraph(f"วันเกิด: {self.selected_day}")
        paragraph(f"เลขคำทำนาย: {self.result_prediction['id']}")
        pygame.draw.line(surface, (0, 0, 0), (margin, y), (width - margin, y), 2)
        y += 18
        centered(self.result_prediction["title"], heading_font, 12)
        paragraph(self.result_prediction["message"], body_font, 16)
        centered("ขอให้พรอันเป็นมงคลนี้ นำพาสิ่งดี ๆ มาสู่ท่าน", small_font, 8)
        centered(datetime.now().strftime("%d/%m/%Y %H:%M:%S"), small_font, 20)

        os.makedirs("printed_receipts", exist_ok=True)
        path = os.path.join(
            "printed_receipts",
            f"fortune_{self.result_prediction['id']}_{datetime.now():%Y%m%d_%H%M%S}.png",
        )
        pygame.image.save(surface.subsurface((0, 0, width, min(y + 30, 1200))), path)
        image = Image.open(path).convert("L")
        image = ImageOps.autocontrast(image).filter(ImageFilter.MinFilter(3))
        image = image.point(lambda pixel: 0 if pixel < 235 else 255, mode="1")
        image.save(path, "PNG", optimize=False)
        return path

    def print_current_result(self):
        if self.result_printed or not self.result_prediction:
            return
        self.result_printed = True
        self.print_status = "กำลังพิมพ์..."
        try:
            receipt_path = self.create_receipt_image()
        except Exception as error:
            self.print_status = "สร้างใบคำทำนายไม่สำเร็จ กรุณาแจ้งพนักงาน"
            print(f"สร้างใบคำทำนายไม่สำเร็จ: {error}")
            return

        def worker():
            try:
                from usb_printer import print_image
                print_image(receipt_path)
                self.print_status = "พิมพ์สำเร็จ กรุณารับใบคำทำนาย"
            except Exception as error:
                self.print_status = "เครื่องพิมพ์ขัดข้อง กรุณาแจ้งพนักงาน"
                print(f"พิมพ์ไม่สำเร็จ: {error}")

        threading.Thread(target=worker, daemon=True).start()

    def handle_gpio_events(self):
        while not gpio_events.empty():
            event_type, value = gpio_events.get()

            if event_type == "day":
                self.select_day(value)
            elif event_type == "spin_down":
                self.start_spin()
            elif event_type == "spin_up":
                self.release_spin()

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return False

            # กดเลข 1-7 เพื่อเลือกวัน
            key_to_day = {
                pygame.K_1: "วันจันทร์",
                pygame.K_2: "วันอังคาร",
                pygame.K_3: "วันพุธ",
                pygame.K_4: "วันพฤหัสบดี",
                pygame.K_5: "วันศุกร์",
                pygame.K_6: "วันเสาร์",
                pygame.K_7: "วันอาทิตย์",
            }

            if event.key in key_to_day:
                self.select_day(key_to_day[event.key])

            if event.key == pygame.K_SPACE:
                self.start_spin()

            if event.key == pygame.K_r and self.state == "RESULT":
                self.reset()

        if event.type == pygame.KEYUP:
            if event.key == pygame.K_SPACE:
                self.release_spin()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = event.pos

            for day, rect in self.day_buttons:
                if rect.collidepoint(mouse_pos):
                    self.select_day(day)
                    return True

            if self.state == "READY" and self.spin_button_rect.collidepoint(mouse_pos):
                self.start_spin()

            if self.state == "RESULT" and self.reset_button_rect.collidepoint(mouse_pos):
                self.reset()

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.release_spin()

        return True

    def reset(self):
        self.selected_day = None
        self.state = "SELECT_DAY"
        self.result_index = None
        self.result_prediction = None
        self.result_printed = False
        self.print_status = ""
        self.spin_speed = 0
        self.is_holding_spin = False
        self.wheel_angle = 0

    def draw_wheel(self):
        center = (370, 365)

        # pygame หมุนค่าบวกทวนเข็มนาฬิกา จึงใส่เครื่องหมายลบเพื่อให้
        # รูปวงล้อหมุนตามเข็มนาฬิกาตรงกับระบบคำนวณเดิม
        rotated_wheel = pygame.transform.rotozoom(
            self.wheel_image,
            -self.wheel_angle,
            1.0,
        )
        wheel_rect = rotated_wheel.get_rect(center=center)
        self.screen.blit(rotated_wheel, wheel_rect)

        # เข็มชี้ด้านบน
        pointer_points = [
            (center[0], 54),
            (center[0] - 27, 112),
            (center[0] + 27, 112),
        ]
        pygame.draw.polygon(self.screen, GOLD, pointer_points)
        pygame.draw.polygon(self.screen, (255, 255, 255), pointer_points, 3)

    def draw_day_buttons(self):
        for day, rect in self.day_buttons:
            is_selected = day == self.selected_day
            color = GREEN if is_selected else PANEL_COLOR

            pygame.draw.rect(self.screen, color, rect, border_radius=12)
            pygame.draw.rect(self.screen, GOLD if is_selected else SUBTEXT_COLOR, rect, 2, border_radius=12)
            draw_text(
                self.screen,
                day,
                self.font_medium,
                TEXT_COLOR,
                rect.centerx,
                rect.centery,
            )

    def draw_right_panel(self):
        pygame.draw.rect(
            self.screen,
            (24, 33, 59),
            pygame.Rect(740, 105, 490, 545),
            border_radius=22,
        )

        if self.state in ("SELECT_DAY", "READY"):
            draw_text(
                self.screen,
                "เลือกวันเกิดของคุณ",
                self.font_large,
                GOLD,
                985,
                135,
            )

            self.draw_day_buttons()

            if self.selected_day:
                message = f"เลือกแล้ว: {self.selected_day}"
                draw_text(self.screen, message, self.font_medium, TEXT_COLOR, 1080, 545)

                button_color = RED if self.state == "READY" else PANEL_COLOR
                pygame.draw.rect(
                    self.screen,
                    button_color,
                    self.spin_button_rect,
                    border_radius=18,
                )
                pygame.draw.rect(
                    self.screen,
                    GOLD,
                    self.spin_button_rect,
                    3,
                    border_radius=18,
                )
                draw_text(
                    self.screen,
                    "กดค้างเพื่อหมุน",
                    self.font_large,
                    TEXT_COLOR,
                    self.spin_button_rect.centerx,
                    self.spin_button_rect.centery,
                )

            else:
                draw_text(
                    self.screen,
                    "กรุณาเลือกวันก่อนเริ่มเล่น",
                    self.font_medium,
                    SUBTEXT_COLOR,
                    985,
                    590,
                )

        elif self.state in ("SPINNING", "SLOWING"):
            draw_text(self.screen, "วงล้อกำลังหมุน", self.font_large, GOLD, 985, 260)

            status = "ปล่อยปุ่มเพื่อให้วงล้อหยุด" if self.state == "SPINNING" else "กำลังรอคำทำนาย..."
            draw_text(self.screen, status, self.font_medium, TEXT_COLOR, 985, 320)

            draw_text(
                self.screen,
                f"วันเกิดที่เลือก: {self.selected_day}",
                self.font_medium,
                SUBTEXT_COLOR,
                985,
                400,
            )

        elif self.state == "RESULT":
            prediction = self.result_prediction

            draw_text(self.screen, "คำทำนายของคุณ", self.font_large, GOLD, 985, 155)
            draw_text(
                self.screen,
                f"วันเกิดที่เลือก: {self.selected_day}",
                self.font_small,
                SUBTEXT_COLOR,
                985,
                205,
            )

            draw_text(
                self.screen,
                f"ช่องที่ {prediction['id']}",
                self.font_medium,
                TEXT_COLOR,
                985,
                255,
            )

            draw_text(
                self.screen,
                prediction["title"],
                self.font_large,
                GREEN,
                985,
                310,
            )

            message_rect = pygame.Rect(785, 350, 400, 150)
            draw_wrapped_text(
                self.screen,
                prediction["message"],
                self.font_medium,
                TEXT_COLOR,
                message_rect,
            )

            if self.print_status:
                draw_text(self.screen, self.print_status, self.font_small,
                          GOLD, 985, 520)

            pygame.draw.rect(
                self.screen,
                BLUE,
                self.reset_button_rect,
                border_radius=14,
            )
            pygame.draw.rect(
                self.screen,
                GOLD,
                self.reset_button_rect,
                2,
                border_radius=14,
            )
            draw_text(
                self.screen,
                "เริ่มใหม่",
                self.font_medium,
                TEXT_COLOR,
                self.reset_button_rect.centerx,
                self.reset_button_rect.centery,
            )

    def draw(self):
        self.screen.fill(BG_COLOR)

        draw_text(
            self.screen,
            "WHEEL OF FORTUNE",
            self.font_title,
            GOLD,
            SCREEN_WIDTH // 2,
            45,
        )

        draw_text(
            self.screen,
            "คำทำนายเพื่อความบันเทิง",
            self.font_small,
            SUBTEXT_COLOR,
            SCREEN_WIDTH // 2,
            82,
        )

        self.draw_wheel()
        self.draw_right_panel()

        pygame.display.flip()

    def run(self):
        running = True

        while running:
            dt = self.clock.tick(FPS) / 1000.0

            self.handle_gpio_events()

            for event in pygame.event.get():
                running = self.handle_event(event)
                if not running:
                    break

            self.update(dt)
            self.draw()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    try:
        setup_gpio()
        app = WheelFortuneApp()
        app.run()

    except Exception as error:
        print(f"เกิดข้อผิดพลาด: {error}")
        pygame.quit()
        sys.exit(1)
