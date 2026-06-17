import os
from typing import Any, List, Union
from ..base import ServiceBase

# 无硬件降级：树莓派 LED 库(rpi_ws281x)只能在 Pi 上跑。
# 在 Windows/纯语音复现时缺这个库属正常，import 失败或显式设 LELAMP_NO_HARDWARE
# 都切到 mock：服务照常起、事件照常收，只是把灯光动作打成日志、不碰 GPIO。
_NO_HARDWARE = os.environ.get("LELAMP_NO_HARDWARE", "").lower() in ("1", "true", "yes")
try:
    from rpi_ws281x import PixelStrip, Color
    _HAS_RPI = True
except Exception:  # ModuleNotFoundError on非树莓派
    _HAS_RPI = False

    def Color(red: int, green: int, blue: int) -> int:  # 兼容占位，便于日志
        return (int(red) << 16) | (int(green) << 8) | int(blue)

_MOCK = _NO_HARDWARE or not _HAS_RPI


class RGBService(ServiceBase):
    def __init__(self,
                 led_count: int = 64,
                 led_pin: int = 12,
                 led_freq_hz: int = 800000,
                 led_dma: int = 10,
                 led_brightness: int = 255,
                 led_invert: bool = False,
                 led_channel: int = 0):
        super().__init__("rgb")

        self.led_count = led_count
        self.mock = _MOCK
        if self.mock:
            self.strip = None
            self.logger.warning(
                "RGBService 运行在无硬件 mock 模式（缺 rpi_ws281x 或 LELAMP_NO_HARDWARE 已设），灯光动作只打日志"
            )
            return
        self.strip = PixelStrip(
            led_count, led_pin, led_freq_hz, led_dma,
            led_invert, led_brightness, led_channel
        )
        self.strip.begin()
        
    def handle_event(self, event_type: str, payload: Any):
        if event_type == "solid":
            self._handle_solid(payload)
        elif event_type == "paint":
            self._handle_paint(payload)
        else:
            self.logger.warning(f"Unknown event type: {event_type}")
    
    def _handle_solid(self, color_code: Union[int, tuple]):
        """Fill entire strip with single color"""
        if self.mock:
            self.logger.info(f"[mock] solid color -> {color_code}")
            return
        if isinstance(color_code, tuple) and len(color_code) == 3:
            color = Color(color_code[0], color_code[1], color_code[2])
        elif isinstance(color_code, int):
            color = color_code
        else:
            self.logger.error(f"Invalid color format: {color_code}")
            return
            
        for i in range(self.led_count):
            self.strip.setPixelColor(i, color)
        self.strip.show()
        self.logger.debug(f"Applied solid color: {color_code}")
    
    def _handle_paint(self, colors: List[Union[int, tuple]]):
        """Set individual pixel colors from array"""
        if self.mock:
            self.logger.info(f"[mock] paint pattern -> {len(colors) if isinstance(colors, list) else '?'} colors")
            return
        if not isinstance(colors, list):
            self.logger.error(f"Paint payload must be a list, got: {type(colors)}")
            return
            
        max_pixels = min(len(colors), self.led_count)
        
        for i in range(max_pixels):
            color_code = colors[i]
            if isinstance(color_code, tuple) and len(color_code) == 3:
                color = Color(color_code[0], color_code[1], color_code[2])
            elif isinstance(color_code, int):
                color = color_code
            else:
                self.logger.warning(f"Invalid color at index {i}: {color_code}")
                continue
                
            self.strip.setPixelColor(i, color)
        
        self.strip.show()
        self.logger.debug(f"Applied paint pattern with {max_pixels} colors")
    
    def clear(self):
        """Turn off all LEDs"""
        if self.mock:
            self.logger.info("[mock] clear LEDs")
            return
        for i in range(self.led_count):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()
    
    def stop(self, timeout: float = 5.0):
        """Override stop to clear LEDs before stopping"""
        self.clear()
        super().stop(timeout)