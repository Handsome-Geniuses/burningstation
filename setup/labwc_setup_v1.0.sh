#!/bin/bash

# To set up, you will need an up-to-date Raspberry Pi OS Bookworm. 
# We have tested this with "2024-07-04-raspios-bookworm-arm64-lite" on a Raspberry Pi 5. Should also work out of the box on a Raspberry Pi 4.
# For ease of use, take Raspberry Pi Imager. Set Wi-Fi, SSH, and hostname as per your needs.
# Then flash your SD card.

# Copy this script to your running Raspberry Pi system and call the script not as a root user:
# bash kiosk_setup.sh

# History
# 2024-10-22 v1.0: Initial release
# 2024-11-04 V1.1: Switch from wayfire to labwc
# 2024-11-13 V1.2: Added setup of wlr-randr 

# Function to display a spinner with additional message
spinner() {
    local pid=$1  # Receive the PID of the background process
    local message=$2  # Receive the message to display with the spinner
    local delay=0.1
    local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")  # spinner frames
    tput civis  # Hide cursor
    local i=0
    while [ -d /proc/$pid ]; do  # Check if the process is still running
        local frame=${frames[$i]}
        printf "\r\e[35m%s\e[0m %s" "$frame" "$message"  # Print spinner frame with the message
        i=$(((i + 1) % ${#frames[@]}))
        sleep $delay
    done
    printf "\r\e[32m✔\e[0m %s\n" "$message"  # Show green checkmark when done
    tput cnorm  # Restore cursor
}

# Check if the script is being run as root, exit if true
if [ "$(id -u)" -eq 0 ]; then
  echo "This script should not be run as root. Please run as a regular user with sudo permissions."
  exit 1
fi

# Get the current username
CURRENT_USER=$(whoami)

# Function to prompt the user for y/n input
ask_user() {
    local prompt="$1"
    while true; do
        read -p "$prompt (y/n): " yn
        case $yn in
            [Yy]* ) return 0;;  # Continue if yes
            [Nn]* ) return 1;;  # Skip if no
            * ) echo "Please answer yes (y) or no (n).";;
        esac
    done
}

# update the package list?
echo
if ask_user "Do you want to update the package list?"; then
    echo -e "\e[90mUpdating the package list, please wait...\e[0m"
    sudo apt update &
    spinner $! "Updating package list..."
fi

# upgrade installed packages?
echo
if ask_user "Do you want to upgrade installed packages?"; then
    echo -e "\e[90mUpgrading installed packages. THIS MAY TAKE SOME TIME, please wait...\e[0m"
    sudo apt upgrade -y &
    spinner $! "Upgrading installed packages..."
fi

# install Wayland/labwc packages?
echo
if ask_user "Do you want to install Wayland and labwc packages?"; then
    echo -e "\e[90mInstalling Wayland packages, please wait...\e[0m"
    sudo apt install --fix-missing --no-install-recommends -y labwc wlr-randr seatd &
    spinner $! "Installing Wayland packages..."
fi

# install Chromium Browser?
echo
if ask_user "Do you want to install Chromium Browser?"; then
    echo -e "\e[90mInstalling Chromium Browser, please wait...\e[0m"
    sudo apt install --fix-missing --no-install-recommends -y chromium-browser &
    spinner $! "Installing Chromium Browser..."
fi

# install and configure greetd?
echo
if ask_user "Do you want to install and configure greetd for auto start of labwc?"; then
    # Install greetd
    echo -e "\e[90mInstalling greetd for auto start of labwc, please wait...\e[0m"
    sudo apt install --fix-missing -y greetd &
    spinner $! "Installing greetd..."

    # Create or overwrite /etc/greetd/config.toml
    echo -e "\e[90mCreating or overwriting config.toml...\e[0m"

    sudo mkdir -p /etc/greetd
    sudo bash -c "cat <<EOL > /etc/greetd/config.toml
[terminal]
vt = 7
[default_session]
command = \"/usr/bin/labwc\"
user = \"$CURRENT_USER\"
EOL"

    echo -e "\e[32m✔\e[0m config.toml has been created or overwritten successfully!"

    # Enable greetd service and set graphical target
    echo -e "\e[90mEnabling greetd service...\e[0m"
    sudo systemctl enable greetd &
    spinner $! "Enabling greetd service..."

    echo -e "\e[90mSetting graphical target as the default...\e[0m"
    sudo systemctl set-default graphical.target &
    spinner $! "Setting graphical target..."
fi

# create an autostart script for labwc?
echo
if ask_user "Do you want to create an autostart (chromium) script for labwc?"; then
    # Ask the user for a default URL
    read -p "Enter the URL to open in Chromium [default: https://webglsamples.org...]: " USER_URL
    USER_URL="${USER_URL:-https://webglsamples.org/aquarium/aquarium.html}"

    # Create or overwrite /etc/greetd/config.toml
    echo -e "\e[90mCreating or overwriting config.toml...\e[0m"
    LABWC_AUTOSTART_DIR="/home/$CURRENT_USER/.config/labwc"
    mkdir -p "$LABWC_AUTOSTART_DIR"
    LABWC_AUTOSTART_FILE="$LABWC_AUTOSTART_DIR/autostart"
    
    # Create or append Chromium start command to the autostart file
    if grep -q "chromium" "$LABWC_AUTOSTART_FILE"; then
        echo "Chromium autostart entry already exists in $LABWC_AUTOSTART_FILE."
    else
        echo -e "\e[90mAdding Chromium to labwc autostart script...\e[0m"
        echo "/usr/bin/chromium-browser --incognito --autoplay-policy=no-user-gesture-required --kiosk $USER_URL &" >> "$LABWC_AUTOSTART_FILE"
    fi
    
    # Provide feedback about the autostart file location
    echo -e "\e[32m✔\e[0m labwc autostart script has been created or updated at $LABWC_AUTOSTART_FILE."
fi


# install Plymouth splash screen?
echo
if ask_user "Do you want to install the Plymouth splash screen?"; then
    # Update /boot/firmware/config.txt
    CONFIG_TXT="/boot/firmware/config.txt"
    if ! grep -q "disable_splash" "$CONFIG_TXT"; then
        echo -e "\e[90mAdding disable_splash=1 to $CONFIG_TXT...\e[0m"
        sudo bash -c "echo 'disable_splash=1' >> $CONFIG_TXT"
    else
        echo -e "\e[33m$CONFIG_TXT already contains a disable_splash option. No changes made. Please check manually!\e[0m"
    fi

    # Update /boot/firmware/cmdline.txt
    CMDLINE_TXT="/boot/firmware/cmdline.txt"
    if ! grep -q "splash" "$CMDLINE_TXT"; then
        echo -e "\e[90mAdding quiet splash plymouth.ignore-serial-consoles to $CMDLINE_TXT...\e[0m"
        sudo sed -i 's/$/ quiet splash plymouth.ignore-serial-consoles/' "$CMDLINE_TXT"
    else
        echo -e "\e[33m$CMDLINE_TXT already contains splash options. No changes made. Please check manually!\e[0m"
    fi

    # Install Plymouth and themes
    echo -e "\e[90mInstalling Plymouth and themes...\e[0m"
    sudo apt install --fix-missing -y plymouth plymouth-themes &
    spinner $! "Installing Plymouth..."

    # List available themes and store them in an array
    echo -e "\e[90mListing available Plymouth themes...\e[0m"
    readarray -t THEMES < <(plymouth-set-default-theme -l)  # Store themes in an array

    # Prompt user to choose a theme
    echo -e "\e[94mPlease choose a theme (enter the number):\e[0m"
    select SELECTED_THEME in "${THEMES[@]}"; do
        if [[ -n "$SELECTED_THEME" ]]; then
            echo -e "\e[90mSetting Plymouth theme to $SELECTED_THEME...\e[0m"
            sudo plymouth-set-default-theme $SELECTED_THEME
            sudo update-initramfs -u &
            spinner $! "Updating initramfs..."
            echo -e "\e[32m✔\e[0m Plymouth splash screen installed and configured with $SELECTED_THEME theme."
            break
        else
            echo -e "\e[31mInvalid selection, please try again.\e[0m"
        fi
    done
fi

# Configure a resolution
echo
if ask_user "Do you want to set the screen resolution in cmdline.txt and the labwc autostart file?"; then

    # Check if edid-decode is installed; if not, install it
    if ! command -v edid-decode &> /dev/null; then
        echo -e "\e[90mInstalling required tool, please wait...\e[0m"
        sudo apt install --fix-missing -y edid-decode &
        spinner $! "Installing edid-decode..."
        echo -e "\e[32mrequired tool installed successfully!\e[0m"
    fi

    # Capture the output of edid-decode command
    edid_output=$(sudo cat /sys/class/drm/card1-HDMI-A-1/edid | edid-decode)

    # Initialize an array to store the formatted resolutions with refresh rates
    declare -a available_resolutions=()

    # Loop through lines and look for timings with resolutions and refresh rates
    while IFS= read -r line; do
        # Match lines with Established, Standard, or Detailed Timings format
        if [[ "$line" =~ ([0-9]+)x([0-9]+)[[:space:]]+([0-9]+\.[0-9]+|[0-9]+)\ Hz ]]; then
            resolution="${BASH_REMATCH[1]}x${BASH_REMATCH[2]}"
            frequency="${BASH_REMATCH[3]}"
            
            # Format as "widthxheight@frequencyHz"
            formatted="${resolution}@${frequency}Hz"
            available_resolutions+=("$formatted")
        fi
    done <<< "$edid_output"

    # Fallback to default list if no resolutions are found
    if [ ${#available_resolutions[@]} -eq 0 ]; then
        echo -e "\e[33mNo resolutions found. Using default list.\e[0m"
        available_resolutions=("1920x1080@60" "1280x720@60" "1024x768@60" "1600x900@60" "1366x768@60")
    fi

    # Prompt user to choose a resolution
    echo -e "\e[94mPlease choose a resolution (type in the number):\e[0m"
    select RESOLUTION in "${available_resolutions[@]}"; do
        if [[ -n "$RESOLUTION" ]]; then
            echo -e "\e[32mYou selected $RESOLUTION\e[0m"
            break
        else
            echo -e "\e[33mInvalid selection, please try again.\e[0m"
        fi
    done

    # Add the selected resolution to /boot/firmware/cmdline.txt if not already present
    CMDLINE_FILE="/boot/firmware/cmdline.txt"
    if ! grep -q "video=" "$CMDLINE_FILE"; then
        echo -e "\e[90mAdding video=HDMI-A-1:$RESOLUTION to $CMDLINE_FILE...\e[0m"
        sudo sed -i "1s/^/video=HDMI-A-1:$RESOLUTION /" "$CMDLINE_FILE"
        echo -e "\e[32m✔\e[0m Resolution added to cmdline.txt successfully!"
    else
        echo -e "\e[33mcmdline.txt already contains a video entry. No changes made.\e[0m"
    fi

    # Add the command to .config/labwc/autostart if not present
    AUTOSTART_FILE="/home/$USER/.config/labwc/autostart"
    if ! grep -q "wlr-randr --output HDMI-A-1 --mode $RESOLUTION" "$AUTOSTART_FILE"; then
        echo "wlr-randr --output HDMI-A-1 --mode $RESOLUTION" >> "$AUTOSTART_FILE"
        echo -e "\e[32m✔\e[0m Resolution command added to labwc autostart file successfully!"
    else
        echo -e "\e[33mAutostart file already contains this resolution command. No changes made.\e[0m"
    fi
fi

# cleaning up apt caches
echo -e "\e[90mCleaning up apt caches, please wait...\e[0m"
sudo apt clean &
spinner $! "Cleaning up apt caches..."

# Print completion message
echo -e "\e[32m✔\e[0m \e[32mSetup completed successfully! Please reboot your system.\e[0m"