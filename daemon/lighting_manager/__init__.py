"""
linux_thermaltake_rgb
Software to control your thermaltake hardware
Copyright (C) 2018  Max Chesterfield (chestm007@hotmail.com)

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""
import time
from threading import Thread

from psutil import sensors_temperatures

from daemon.lighting_manager.utils.colours import compass_to_rgb


def lighting_controller_factory(*args, **kwargs):
    effect = None
    if not args:
        kwargs = dict(kwargs)
        _type = kwargs.pop('type')
    else:
        args = list(args)
        _type = args.pop(0)

    if _type == 'static':
        effect = StaticLightingEffect(*args, **kwargs)
    elif _type == 'alternating':
        effect = AlternatingLightingEffect(*args, **kwargs)
    elif _type == 'rgb_spectrum':
        effect = RGBSpectrumLightingEffect()
    elif _type == 'spinning_rgb_spectrum':
        effect = SpinningRGBSpectrumLightingEffect()
    elif _type == 'temperature':
        effect = TemperatureLightingEffect(*args, **kwargs)

    if effect is not None:
        return LightingController(effect)


class LightingEffect:
    def __iter__(self):
        return self

    def begin_dev(self):
        pass

    def begin_all(self):
        pass

    def next(self):
        raise NotImplementedError


class StaticLightingEffect(LightingEffect):
    def __init__(self, r: int, g: int, b: int):
        self.r, self.g, self.b = r, g, b

    def next(self):
        return self.g, self.r, self.b


class AlternatingLightingEffect(LightingEffect):
    def __init__(self, even_rgb_matrix, odd_rgb_matrix):
        self.even_r, self.even_g, self.even_b = even_rgb_matrix
        self.odd_r, self.odd_g, self.odd_b = odd_rgb_matrix
        self.odd = True

    def next(self):
        if self.odd:
            self.odd = False
            return self.odd_g, self.odd_r, self.odd_b
        else:
            self.odd = True
            return self.even_g, self.even_r, self.even_b


class RGBSpectrumLightingEffect(LightingEffect):
    def __init__(self):
        self.num_iters = 0
        self.compass_to_rgb_map = [compass_to_rgb(ang) for ang in range(360)]

    def begin_dev(self):
        self.num_iters = 0

    def next(self):
        self.num_iters += 1
        return self.compass_to_rgb_map[int(360/12*self.num_iters)]


class SpinningRGBSpectrumLightingEffect(RGBSpectrumLightingEffect):
    def __init__(self):
        super().__init__()
        self.rotation = 0

    def begin_all(self):
        if self.rotation > 11:
            self.rotation = 0
        self.rotation += 1

    def next(self):
        self.num_iters += 1
        return compass_to_rgb((360/12*self.num_iters) + 360/12*self.rotation)


class TemperatureLightingEffect(LightingEffect):
    def __init__(self, sensor_name, hot: int=60, target: int=30, cold: int=20):
        self.sensor_name = sensor_name
        self.cur_temp = 0
        self.angle = 0

        self.cold = cold
        self.target = target
        self.hot = hot

        self.cold_angle = 240
        self.target_angle = 120
        self.hot_angle = 0

    def begin_all(self):
        print(self.angle)
        self.cur_temp = sensors_temperatures().get(self.sensor_name)[0].current
        if self.cur_temp <= self.cold:
            self.angle = self.cold_angle
        elif self.cur_temp < self.target:
            self.angle = ((self.cold_angle - self.target_angle)
                          / (self.target - self.cold)
                          * (self.target - self.cur_temp))
        elif self.cur_temp == self.target:
            self.angle = self.target_angle
        elif self.cur_temp > self.hot:
            self.angle = self.hot_angle
        elif self.cur_temp > self.target:
            self.angle = 120 - ((self.target_angle - self.hot_angle)
                                / (self.hot - self.target)
                                * (self.cur_temp - self.target))

    def next(self):
        return compass_to_rgb(self.angle)


class LightingController:
    def __init__(self, lighting_effect):
        self.lighting_effect = lighting_effect
        self.brightness_level = 100
        self.update_msec = 100

    def main(self, device) -> tuple:
        """
        returns a hex array to set the lights too
        """
        data = []
        self.lighting_effect.begin_dev()
        for i in range(device.num_leds):
            data.extend(self._brightness_processor(self.lighting_effect.next()))
        return data, self.update_msec

    def _brightness_processor(self, rgb):
        if self.brightness_level == 0:
            return [0, 0, 0]
        else:
            return [int(i/100*self.brightness_level) for i in rgb]


class LightingManager:
    def __init__(self, initial_controller: LightingController=None):
        self._continue = False
        self._thread = Thread(target=self._main_loop)
        self._devices = []
        self._controller = initial_controller

    def attach_device(self, device):
        self._devices.append(device)

    def set_controller(self, controller: LightingController):
        if isinstance(controller, LightingController):
            self._controller = controller

    def set_brightness(self, brightness: int):
        if brightness < 0:
            brightness = 0
        elif brightness > 300:
            brightness = 300
        self._controller.brightness_level = int(brightness)

    def set_light_update_msec(self, sec: int):
        if sec > 0:
            self._controller.update_msec = int(sec)

    def _main_loop(self):
        next_poll_msec  = 1
        while self._continue:
            self._controller.lighting_effect.begin_all()
            for dev in self._devices:
                data, next_poll_msec = self._controller.main(dev)
                dev.set_lighting(data)
            time.sleep(next_poll_msec / 1000)

    def start(self):
        self._continue = True
        self._thread.start()

    def stop(self):
        self._continue = False
        self._thread.join()
