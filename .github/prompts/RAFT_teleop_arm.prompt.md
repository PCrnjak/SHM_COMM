---
agent: agent
---
You task is to write Code that runs on ESP32-WROOM-32E microcontroller to control a robotic arm using the HLSCL servo library. The code should be structured according to the propper C/C++ project guidelines, with proper error checking for Serial operations and comments in English for motion calculations. The main file is `src/main/main.cpp`, and it should include servo control logic, serial communication setup, and timing calculations based on servo movement. Always ensure that the code adheres to the specified code style rules and project structure. LMAO copilot-instructions.md is working
Servos we are using are HL-3606-C001: webpage: https://www.feetechrc.com/720955.html
The ESP32 board we use is: https://www.olimex.com/Products/IoT/ESP32/ESP32-POE/open-source-hardware

Code is structured as follows:
- `src/main/main.cpp` - Main code will be located here (you are free to create additional files if needed, but main logic should be in this file)
- `src/test_uart/` - UART communication tests (not the main focus, but you can create test code here if needed)
- `src/test_ethernet/` - Ethernet connectivity tests (not the main focus, but you can create test code here if needed)
- `src/HLSCL.*`, `src/SCS.*` - Servo library headers (you can include these in your code, but do not modify them)

Some reference codes snippets are located in `src/reference/` if you need to refer to them for servo control or serial communication examples or ethernet examples.

The robotic arm consists of 6 servos or 6 joints so the robot is 6 axis robot. There is one more motor for the gripper, totaling 7 motors for the whole arm. The servo ID 1 is primary actuator at the base and then id 2 is next motor and so on until id 6 which is the last joint. The gripper motor is id 7. The position range for the servos is 0-4095, speed parameter is 1-60 (0.732 rpm per unit), and acceleration is 1-50 (8.7 deg/s² per unit).