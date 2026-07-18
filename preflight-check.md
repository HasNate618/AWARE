## Demo / Workshop preflight check

## Objective

To ensure a consistent and effective workshop and demo, focusing on the Arduino UNO Q platform, while addressing common challenges such as Wi-Fi connectivity and software setup.

(based on a paper fromTyler "Wojo")

## Preparation

- Ensure all participants have the Arduino tools pre-installed on their machines. Provide detailed pre-work instructions, including the use of arduino-flasher-cli download latest to download the latest Debian image &amp; share a copy\_of thepresentation ahead of time
- Ensure all participants have reviewed the Uno Q User Guide
- [. Review the Uno Q"First Use' User Manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/#first-use)
- . Provide installation verification checklist including Arduino App Lab version (&gt;=0.2.4), arduino-flasher-cli Tool version (&gt;= 0.4.0)
- .Share direct download links for Debian images as backup: https://downloads.arduino.cc/debian-im/Stable/info.json
- . Share Uno Q block diagram and component descriptions for reference, alongside pinout diagram and direct link to Uno Q Product Landing Page where participants may download datasheet,schematic,etc.
- Optionally, create an Arduino Cloud Account alongside an Edge Impulse Account and save credentials to something like a password manager
- ·Optionally download ADB
- 。 Linux ARM: https://downloads.arduino.cc/tools/android/adb\_r32.0.0-linuxaarch64.tar.bz2

Linux x86:https://downloads.arduino.cc/tools/android/adb\_r32.0.0-linux64.tar.bz2

macOs: https://downloads.arduino.cc/tools/android/platform-tools\_r32.0.0-darwin.zip

Windows: https://downloads.arduino.cc/tools/android/platform-tools\_r32.0.0-windows.zip

## SetupModesDefined

Single-Board Computer Mode

## Wi-FiSetup

- connectivity issues
- ·. Consider deploying an enterprise Wi-Fi cellular router onsite for reliable internet access
- .Test bandwidth requirements: reccomended 10 Mbps per participant for smooth downloads (use speedtest.net)
- . Create fallback hotspot plan using mobile devices with clear SSID naming convention

## Hardware Preparation

- . Ensure all UNO Q units are flashed and tested prior to the training session
- . Prepare backup units in case of flashing failure
- Label each unit with version number and last flash date
- . Include jumper wires for manual flashing if needed

## Addressing Wi-Fi Connectivity and Technical Challenges

- . Use Single-Board Computer Mode (Standalone Mode) for UNO Q to minimize dependency
- Ensure both the laptop and UNO Q are on the same Wi-Fi network. Use terminal commands to configureWi-Fi if necessary
- . Terminal command reference:
- sudo nmcli d wifi connect Arduino password Arduino#1
- . Document boot time expectations: 15-30 seconds for Debian image, watch for LED matrix heartbeat animation
- . "10-Minute Rule" If a participant cannot flash/connect within ~10min, the instruction should be to swap the unit immediately with a spare to keep the training on schedule

## SoftwareVersion Management

- . Ensure the App Lab software version matches the UNO Q version to avoid update issues

PC Hosted Mode

- Recommend uninstalling and reinstalling the latest App Lab version if discrepancies occur
- . Maintain version compatibility matrix between App Lab, firmware, and Debian image
- . Document known version conflicts and workarounds

## TroubleshootingGuide

## "Waiting for board to be connected" message

- . Verify USB cable is data-capable (not charge-only)

## Slowdownload speeds

- . Pre-download images using browser if CLI fails
- .Use arduino-flasher-cli download latest during pre-work
- . Captive portal interference
- . Switch to mobile hotspot
- . Use Single-Board Computer Mode (Standalone Mode) to reduce connectivity requirements

## Update chainfailures

- . Uninstall and reinstall App Lab rather than updating
- . Flash manually using jumper method with Flash Tool, if needed
- . Remove the jumper wire before the final reboot of successful Flasher Tool board flash
- . If the board is not recognized OR if flasher tool throws and error consider to change the usb cable from USB-C → USB-C to USB-A to USB-C cable (this happened with windows laptop)

## Post-TrainingAssessment

## Feedback Collection

- . Gather feedback from participants on their experience and any challenges faced
- . Document any technical issues and potential solutions for future sessions
- . Use standardized feedback (Google Form) covering technical issues, content clarity, and practical application

## ContinuousImprovement

- . Review feedback with the product team to refine the training process and address any recurring issues.
- Update the SOP as needed based on new insights and technological advancements.
- .Maintain issue tracker on GitHub for arduino-flasher-cli improvements

## SuccessMetrics

- . 100% of participants with pre-installed tools
- . 10o% successful board flashing during session
- . 100% understanding of UNO Q value proposition
- ·Each participant identifies 3+ customer opportunities
- &lt; 5 minute setup time per participant in optimal conditions

## Pre-Work Checklist Template

- [ ] [] arduino-flasher-cli installed and tested (&gt;= 0.4.0 version)

- [ ] [ ] Arduino App Lab installed (&gt;= 0.2.0 version)

- [ ] [ ] Debian image pre-downloaded using arduino-flasher-cli download latest

- [ ] [ ] Test Wi-Fi connectivity at home/office

- [ ] []ReviewUNOQdocumentation

WorkshopMaterialsChecklist

- [ ] [ ] UNO Q boards (1 per participant + 25% spares)

- [ ] []USB-C cables (USB-C to USB A preferred)

- [ ] [ ] *USB-C Hub (if using additional powered peripherals)

- [ ] [ ] F-F Jumper wires for manual flashing

- [ ] [ ] Mobile hotspot or cellular router for redundancy and/or bypass firewalls temporarily

- [ ] [ ] Accessible quick reference guides and other resources provided in the pre-training documentation

- [ ] [ ] Customer engagement templates, "sell sheets," "battle cards" and other sales tools
