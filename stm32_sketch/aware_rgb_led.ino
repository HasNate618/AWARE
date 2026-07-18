// AWARE RGB LED + sensor firmware for STM32U585
//
// Wiring: R -> D5 (~PWM), G -> D9 (~PWM), B -> D11 (~PWM)
//         common cathode -> GND (or anode -> 3.3V for common anode)
//
// Compile & upload (on board):
//   arduino-cli compile -b arduino:zephyr:unoq stm32_sketch/
//   arduino-cli upload -b arduino:zephyr:unoq -p /dev/ttyACM0 stm32_sketch/

#include <Arduino_RPCLite.h>

const int PIN_LED_R = 5;
const int PIN_LED_G = 9;
const int PIN_LED_B = 11;

SerialServer server;

void setup() {
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);

  Serial1.begin(115200);
  server.begin(Serial1);

  // set_rgb(r, g, b) — discrete RGB LED on fixed pins
  server.registerMethod("set_rgb", [](const Variant& args) -> Variant {
    int r = constrain(args[0].as<int>(), 0, 255);
    int g = constrain(args[1].as<int>(), 0, 255);
    int b = constrain(args[2].as<int>(), 0, 255);
    analogWrite(PIN_LED_R, r);
    analogWrite(PIN_LED_G, g);
    analogWrite(PIN_LED_B, b);
    return Variant(true);
  });

  // set_led_pwm(pin_r, pin_g, pin_b, r, g, b) — arbitrary PWM pins
  server.registerMethod("set_led_pwm", [](const Variant& args) -> Variant {
    int pin_r = args[0].as<int>();
    int pin_g = args[1].as<int>();
    int pin_b = args[2].as<int>();
    int r = constrain(args[3].as<int>(), 0, 255);
    int g = constrain(args[4].as<int>(), 0, 255);
    int b = constrain(args[5].as<int>(), 0, 255);
    analogWrite(pin_r, r);
    analogWrite(pin_g, g);
    analogWrite(pin_b, b);
    return Variant(true);
  });

  // Legacy Modulino Pixel RPC (for compatibility with SerialMCU)
  server.registerMethod("set_led", [](const Variant& args) -> Variant {
    // index, r, g, b, brightness
    // TODO: wire up Modulino Pixels via Wire1
    return Variant(true);
  });

  // Sensor stubs — return mock values until Modulino libraries are included
  server.registerMethod("read_temp", [](const Variant&) -> Variant {
    return Variant(22.5f);
  });

  server.registerMethod("read_distance", [](const Variant&) -> Variant {
    return Variant(150.0f);
  });

  server.registerMethod("read_all", [](const Variant&) -> Variant {
    return Variant(42);  // placeholder
  });
}

void loop() {
  server.poll();
}
