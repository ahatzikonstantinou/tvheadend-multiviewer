#!/bin/bash

# Replace these variables with your actual values
PI_USERNAME="antonis"
PI_HOST="192.168.3.10"
PI_DESTINATION="/opt/ehome_v3.0/"

# Function to display usage information
usage() {
    echo "Usage: $0 <project_folder>"
    exit 1
}

# Check if project folder is provided
if [ $# -eq 0 ]; then
    usage
fi

# Check if SSH is installed
if ! command -v ssh &> /dev/null; then
    echo "SSH is not installed. Please install SSH on your system."
    exit 1
fi

# Check if project folder exists
if [ ! -d "$1" ]; then
    echo "Project folder '$1' does not exist."
    usage
fi

# Define the folders and files relative to the project folder
PROJECT_FOLDER="$1"

SOURCE_FOLDERS=(
    "static"
    "templates"
)

SOURCE_FILES=(
    "main.py"
    "filREADME.md"
    "RFLink.py"
    "rflink_item.py"
)

# Copy files to Raspberry Pi
echo "Copying files to Raspberry Pi..."
for src_dir in "${SOURCE_FOLDERS[@]}"; do
    src_path="$PROJECT_FOLDER/$src_dir"
    if [ ! -d "$src_path" ]; then
        echo "Source directory '$src_path' does not exist."
        continue
    fi

    echo "Copying files from '$src_path'..."
    scp -r "$src_path" "$PI_USERNAME@$PI_HOST:$PI_DESTINATION"
    
    # Check if SCP was successful
    if [ $? -eq 0 ]; then
        echo "Files copied successfully."
    else
        echo "Failed to copy files from '$src_path'."
    fi
done

for src_file in "${SOURCE_FILES[@]}"; do
    src_path="$PROJECT_FOLDER/$src_file"
    if [ ! -f "$src_path" ]; then
        echo "Source file '$src_path' does not exist."
        continue
    fi

    echo "Copying file '$src_path'..."
    scp "$src_path" "$PI_USERNAME@$PI_HOST:$PI_DESTINATION"
    
    # Check if SCP was successful
    if [ $? -eq 0 ]; then
        echo "File copied successfully."
    else
        echo "Failed to copy file '$src_path'."
    fi
done

exit 0
