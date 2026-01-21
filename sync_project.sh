#!/bin/bash

# Replace these variables with your actual values
DEFAULT_PI_USERNAME="antonis"
DEFAULT_PI_HOST="192.168.3.104"
PI_DESTINATION="/opt/tv-mosaic/"

# Function to display usage information
usage() {
    echo "Usage: $0 <project_folder> [username] [host]"
    echo "Example: $0 /path/to/project antonis 192.168.3.104"
    exit 1
}

# Check if project folder is provided
if [ $# -eq 0 ]; then
    usage
fi

# Check if rsync is installed
if ! command -v rsync &> /dev/null; then
    echo "rsync is not installed. Please install rsync on your system."
    sleep 5
    exit 1
fi

# Check if project folder exists
if [ ! -d "$1" ]; then
    echo "Project folder '$1' does not exist."
    usage
fi

# Define the project folder
PROJECT_FOLDER="$1"
PI_USERNAME="${2:-$DEFAULT_PI_USERNAME}"
PI_HOST="${3:-$DEFAULT_PI_HOST}"

# Define the list of files and folders to be copied
SOURCE_FOLDERS=(
    "static"
)

SOURCE_FILES=(
    "app.py"
)

# Copy files to Raspberry Pi using rsync
echo "Copying files to Raspberry Pi..."
rsync -avz --progress --exclude='.*' "${SOURCE_FOLDERS[@]}" "${SOURCE_FILES[@]}" "$PI_USERNAME@$PI_HOST:$PI_DESTINATION"

# Check if rsync was successful
if [ $? -eq 0 ]; then
    echo "Files copied successfully."
else
    echo "Failed to copy files."
    exit 1
fi

exit 0
