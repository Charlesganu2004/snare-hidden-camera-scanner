# config.py
# Raspberry Pi Pico 2 W wiring configuration

# --- Motor Driver ---
# Motor PWM was moved to GP14 so it no longer collides with the second ultrasonic trigger pin.
MOTOR_AIN1 = 13    # GP13 -> Ain1
MOTOR_AIN2 = 12    # GP12 -> Ain2
MOTOR_PWM  = 14    # GP14 -> PWMA
MOTOR_STBY = 15    # GP15 -> STBY

# --- Ultrasonic Sensors (HC-SR04) ---
ULTRA1_TRIG = 8    # GP8 -> Device 1 Trig
ULTRA1_ECHO = 9    # GP9 -> Device 1 Echo

# The second trigger remains on GP16 now that the PWM conflict has been removed.
ULTRA2_TRIG = 16   # GP16 -> Device 2 Trig
ULTRA2_ECHO = 17   # GP17 -> Device 2 Echo

ULTRA3_TRIG = 20   # GP20 -> Device 3 Trig
ULTRA3_ECHO = 21   # GP21 -> Device 3 Echo

ULTRA4_TRIG = 26   # GP26 -> Device 4 Trig
ULTRA4_ECHO = 27   # GP27 -> Device 4 Echo

# --- IR Sensors (D6T-8L-09H) ---
# Device 1
IR1_SDA = 5        # GP5 -> LV1 -> HV1 -> D6T SDA
IR1_SCL = 4        # GP4 -> LV2 -> HV2 -> D6T SCL

# Device 2
IR2_SDA = 18       # GP18 -> LV4 -> HV4 -> D6T SDA
IR2_SCL = 19       # GP19 -> LV3 -> HV3 -> D6T SCL

# --- GPS (NEO-6M) ---
GPS_TX = 0         # GP0 -> GPS Tx
GPS_RX = 1         # GP1 -> GPS Rx

# --- Button ---
BUTTON_PIN = 7     # GP7 -> momentary tactile button

# --- LEDs ---
RED_LED_PIN   = 2   # GP2 -> external Red LED
GREEN_LED_PIN = "LED"  # onboard Pico LED

# --- Local Access Point ---
# This AP name is shown to the user before Wi-Fi is configured on the Pico.
AP_SSID = "SNARE_Device_101"
AP_PASSWORD = "12345678"
WIRELESS_COUNTRY = "US"
AP_CHANNEL = 6

# --- Encrypted Storage ---
# This local storage secret is used to encrypt scan data before it sits on the Pico.
# This secret should be changed before deploying production hardware.
STORAGE_SECRET = "secret"
