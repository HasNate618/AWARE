#include <Arduino_RouterBridge.h>
#include <Wire.h>
#include <Arduino_Modulino.h>
#include <math.h>

ModulinoThermo thermo;
ModulinoDistance dist;
ModulinoMovement move;

bool has_dist = false;

float cached_temp = 0;
float cached_dist = 0;
float cached_ax = 0, cached_ay = 0, cached_az = 0;

float read_temp()     { return cached_temp; }
float read_distance() { return cached_dist; }
float accel_x()       { return cached_ax; }
float accel_y()       { return cached_ay; }
float accel_z()       { return cached_az; }

float movement_intensity() {
    float mag = sqrt(cached_ax * cached_ax + cached_ay * cached_ay + cached_az * cached_az);
    float intensity = mag - 1.0;
    return intensity < 0 ? 0 : intensity;
}

void setup() {
    Bridge.begin(115200);
    Bridge.provide_safe("read_temp", read_temp);
    Bridge.provide_safe("read_distance", read_distance);
    Bridge.provide_safe("accel_x", accel_x);
    Bridge.provide_safe("accel_y", accel_y);
    Bridge.provide_safe("accel_z", accel_z);
    Bridge.provide_safe("movement_intensity", movement_intensity);

    Modulino.begin(Wire1);
    thermo.begin();
    has_dist = dist.begin();
    move.begin();
}

void loop() {
    cached_temp = thermo.getTemperature();

    if (has_dist && dist.available()) {
        cached_dist = dist.get();
    }

    move.update();
    cached_ax = move.getX();
    cached_ay = move.getY();
    cached_az = move.getZ();

    delay(20);
}
